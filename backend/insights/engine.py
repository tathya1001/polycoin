"""The chart engine: a validated spec and plain rows in, a small result out.

Pure Python: no Django, no database, no HTTP. Money is Decimal throughout and leaves the
engine as strings. Rows are dicts with the keys date, txn_type, category_name, source (a
balances.SourceLabel), amount, name and balance, and the specs it reads are produced by
`insights.spec.validate_spec`.
"""

from collections.abc import Callable
from datetime import date, timedelta
from decimal import Decimal
from functools import partial

from .balances import closing_balance
from .formula import (
    FORMULA,
    PanelView,
    Span,
    current_view,
    days_in,
    evaluate_rows,
    panel_view,
    parse_once,
)

GRANULARITIES = ("day", "week", "month", "quarter", "year")
MEASURES = ("spend", "income", "net", "amount", "count", "balance")
AGGS = ("sum", "avg", "min", "max", "median", "count", "last")
DIMENSIONS = (
    "date", "weekday", "month_of_year", "category", "txn_type", "merchant", "data_source",
)  # fmt: skip
GROUPED_CHARTS = ("bar", "line", "area", "pie", "donut")

OTHER_LABEL = "Other"
CALENDAR_MAX_DAYS = 366  # keep equal to spec.CALENDAR_MAX_DAYS
# More time buckets than this is unreadable as a chart, and an unbounded range
# (say 2000 to 2100 by day) would let one request build a huge list.
MAX_BUCKETS = 1000


class TooManyBuckets(ValueError):
    """The period holds more time buckets than a chart can sensibly show."""


class PeriodTooLong(ValueError):
    """A calendar heatmap was asked to draw more days than fit in a year."""


# --- time buckets -------------------------------------------------------------


def bucket_date(d: date, granularity: str) -> date:
    """The first day of the bucket `d` falls in. Weeks start on Monday (ISO)."""
    if granularity == "day":
        return d
    if granularity == "week":
        return d - timedelta(days=d.weekday())
    if granularity == "month":
        return d.replace(day=1)
    if granularity == "quarter":
        return d.replace(month=3 * ((d.month - 1) // 3) + 1, day=1)
    if granularity == "year":
        return d.replace(month=1, day=1)
    raise ValueError(f"Unknown granularity: {granularity!r}")


def add_months(d: date, months: int) -> date:
    """The first of the month `months` later (negative goes back). Expects a day-1 date."""
    index = d.year * 12 + (d.month - 1) + months
    return date(index // 12, index % 12 + 1, 1)


def next_bucket(d: date, granularity: str) -> date:
    """The start of the bucket after the one starting at `d`."""
    if granularity == "day":
        return d + timedelta(days=1)
    if granularity == "week":
        return d + timedelta(days=7)
    if granularity == "month":
        return add_months(d, 1)
    if granularity == "quarter":
        return add_months(d, 3)
    if granularity == "year":
        return add_months(d, 12)
    raise ValueError(f"Unknown granularity: {granularity!r}")


def bucket_range(start: date, end: date, granularity: str) -> list[date]:
    """Every bucket start from the bucket containing `start` to the one containing `end`.

    Raises TooManyBuckets past MAX_BUCKETS, before building the rest of the list.
    """
    current = bucket_date(start, granularity)
    last = bucket_date(end, granularity)
    buckets = []
    while current <= last:
        if len(buckets) >= MAX_BUCKETS:
            raise TooManyBuckets(f"More than {MAX_BUCKETS} {granularity} buckets in the period.")
        buckets.append(current)
        current = next_bucket(current, granularity)
    return buckets


def previous_bucket(d: date, granularity: str) -> date:
    """The start of the bucket before the one starting at `d`."""
    return bucket_date(d - timedelta(days=1), granularity)


def year_before(d: date) -> date:
    """The same calendar day a year earlier; 29 February becomes the 28th."""
    try:
        return d.replace(year=d.year - 1)
    except ValueError:
        return d.replace(year=d.year - 1, day=28)


def comparison_periods(kpi: dict, period: tuple[date, date]) -> list[tuple[date, date]]:
    """The periods a KPI is compared with: none, the one before, the same dates a year earlier,
    or the N periods of the same length before it (their average is the baseline)."""
    compare = kpi["compare"]
    if compare == "previous":
        return [previous_period(period)]
    if compare == "year_ago":
        return [(year_before(period[0]), year_before(period[1]))]
    if compare == "average":
        periods, current = [], period
        for _ in range(kpi["average_of"]):
            current = previous_period(current)
            periods.append(current)
        return periods
    return []


def load_start(spec: dict, period: tuple[date, date]) -> date:
    """The first day of rows a panel needs: its own period, or earlier when it looks back.

    A KPI that compares needs the periods it compares with; a moving average needs the buckets
    that fill its first window; a change needs the bucket before, or the same bucket a year
    earlier.
    """
    kpi = spec.get("kpi")
    if kpi:
        return min((start for start, _ in comparison_periods(kpi, period)), default=period[0])
    calc = spec.get("calc")
    if not calc or calc["type"] not in ("moving_average", "change"):
        return period[0]
    granularity = spec["x"]["granularity"]
    first = bucket_date(period[0], granularity)
    if calc["type"] == "change" and calc["vs"] == "year_ago":
        return bucket_date(year_before(first), granularity)
    steps = calc["window"] - 1 if calc["type"] == "moving_average" else 1
    for _ in range(steps):
        first = previous_bucket(first, granularity)
    return first


# --- measures and aggregation -------------------------------------------------


def measure_value(row: dict, measure: str) -> Decimal | None:
    """The number this row contributes to `measure`, or None if it doesn't contribute."""
    amount = row["amount"]
    is_debit = row["txn_type"] == "debit"

    if measure == "spend":
        return amount if is_debit else None
    if measure == "income":
        return None if is_debit else amount
    if measure == "net":
        return -amount if is_debit else amount
    if measure == "amount":
        return amount
    if measure == "count":
        return Decimal(1)
    if measure == "balance":
        return row["balance"]  # may itself be None: not every statement has a balance column
    raise ValueError(f"Unknown measure: {measure!r}")


def aggregate(values: list[Decimal], agg: str) -> Decimal | None:
    """Collapse `values` to one number. None means 'undefined' (e.g. the average of nothing).

    `last` returns the final value, so the caller must pass values in date order.
    """
    if agg not in AGGS:
        raise ValueError(f"Unknown aggregation: {agg!r}")

    if agg == "count":
        return Decimal(len(values))
    if agg == "sum":
        return sum(values, Decimal(0))
    if not values:
        return None

    if agg == "avg":
        return sum(values, Decimal(0)) / len(values)
    if agg == "min":
        return min(values)
    if agg == "max":
        return max(values)
    if agg == "last":
        return values[-1]

    ordered = sorted(values)  # median
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


# --- grouping -----------------------------------------------------------------


def group_days(dims: list[tuple[str, str | None]], key: tuple, start: date, end: date) -> int:
    """The calendar days one group covers: the days from start to end that its keys allow.

    A month bucket covers its own days, cut to the range. A weekday or month-of-year group
    covers those days in the range. A category, type or merchant group covers the whole range.
    """
    weekdays = months = None
    for (field, granularity), value in zip(dims, key, strict=True):
        if field == "date":
            start = max(start, value)
            end = min(end, next_bucket(value, granularity) - timedelta(days=1))
        elif field == "weekday":
            weekdays = {value}
        elif field == "month_of_year":
            months = {value}
    return days_in(start, end, weekdays, months)


def _bucket_end(bucket: date, granularity: str, end: date) -> date:
    return min(end, next_bucket(bucket, granularity) - timedelta(days=1))


def group_span(
    dims: list[tuple[str, str | None]], key: tuple, start: date, end: date
) -> Callable[[], int]:
    """The days one group covers, for the group's calculated values.

    A group split only by time also knows its last day, which is what a balance is read at. Any
    other group is a slice of the rows, so a balance there comes from those rows alone.
    """
    count = partial(group_days, dims, key, start, end)
    if len(dims) == 1 and dims[0][0] == "date":
        return Span(count, _bucket_end(key[0], dims[0][1], end))
    return count


def dimension_key(row: dict, dimension: str, granularity: str | None = None):
    """Which group `row` belongs to for this dimension. The result must be hashable."""
    if dimension == "date":
        if granularity is None:
            raise ValueError("The date dimension needs a granularity.")
        return bucket_date(row["date"], granularity)
    if dimension == "weekday":
        return row["date"].weekday()  # 0 = Monday ... 6 = Sunday
    if dimension == "month_of_year":
        return row["date"].month  # 1..12, across all years
    if dimension == "category":
        return row["category_name"]
    if dimension == "txn_type":
        return row["txn_type"]
    if dimension == "merchant":
        # "TASTYBITES", "tastybites " and "Tastybites" are one merchant.
        return " ".join(row["name"].split()).title()
    if dimension == "data_source":
        return row["source"].name
    raise ValueError(f"Unknown dimension: {dimension!r}")


def group_rows(
    rows: list[dict], dimensions: list[tuple[str, str | None]]
) -> dict[tuple, list[dict]]:
    """Sort rows into groups. `dimensions` is a list of (dimension, granularity) pairs.

    The key is a tuple with one entry per dimension, so a chart split by category AND by
    month gets keys like ("Food", date(2026, 10, 1)). With no dimensions there is one
    group, (), holding every row. That is exactly what a KPI number needs.
    """
    groups: dict[tuple, list[dict]] = {}
    for row in rows:
        key = tuple(
            dimension_key(row, dimension, granularity) for dimension, granularity in dimensions
        )
        groups.setdefault(key, []).append(row)
    return groups


def top_n(pairs: list[tuple], n: int, fold: bool = True) -> list[tuple]:
    """Keep the `n` largest (label, value) pairs, biggest first.

    With `fold`, everything else is summed into one trailing ("Other", total) pair so the
    chart's total is unchanged. Only fold values that can be added up (sum, count). Folding
    an average or a maximum into "Other" would be meaningless, so callers pass fold=False.
    """
    if n < 1:
        raise ValueError("n must be at least 1.")

    ranked = sorted(pairs, key=lambda pair: pair[1], reverse=True)  # stable: ties keep order
    kept, rest = ranked[:n], ranked[n:]
    if rest and fold:
        kept.append((OTHER_LABEL, sum((value for _, value in rest), Decimal(0))))
    return kept


def histogram(values: list[Decimal], bins: int) -> list[tuple[Decimal, Decimal, int]]:
    """Equal-width bins between min and max, as (start, end, count). Counts add up to len(values).

    Every bin is [start, end) except the last, which also includes the maximum.
    """
    if bins < 1:
        raise ValueError("bins must be at least 1.")
    if not values:
        return []

    low, high = min(values), max(values)
    if low == high:  # no spread to divide: one bin holds everything
        return [(low, high, len(values))]

    width = (high - low) / bins
    counts = [0] * bins
    for value in values:
        index = int((value - low) / width)  # which bin; int() rounds down for non-negatives
        # The maximum lands exactly on `bins`, one past the end: fold it into the last bin.
        counts[min(index, bins - 1)] += 1

    return [
        (low + width * i, high if i == bins - 1 else low + width * (i + 1), counts[i])
        for i in range(bins)
    ]


# --- runners ------------------------------------------------------------------


def _y_cell(rows: list[dict], y: dict, days: Callable[[], int] | None = None) -> Decimal | None:
    """One aggregated number for a group of rows, or None if no row contributes.

    None means "nothing to show here", not zero: a Salary group has no *spend*, so it must
    not appear in a spend chart. Real zeros for empty time buckets are added later, where
    run_grouped fills the gaps. `days` gives the calendar days the group covers; only a
    calculated field that uses `days` calls it.
    """
    if y["measure"] == FORMULA:  # worked out from the whole group, not row by row
        return evaluate_rows(y["formula"]["expression"], rows, days) if rows else None
    if y["measure"] == "balance":
        book, last = current_view().book, getattr(days, "last", None)
        return closing_balance(rows) if book is None or last is None else book.at(last)
    values = []
    for row in rows:
        value = measure_value(row, y["measure"])
        if value is not None:
            values.append(value)
    if not values:
        return None
    return aggregate(values, y["agg"])


def value_of(rows: list[dict], y: dict, days: Callable[[], int] | None = None) -> str | None:
    """The one number a panel's measure gives for `rows`, formatted as the charts format it."""
    return _fmt(_or_zero(_y_cell(rows, y, days), y), y)


def _money(value: Decimal) -> str:
    """Two decimal places, as a string, so the browser never rounds money through floats."""
    return str(value.quantize(Decimal("0.01")))


def _fmt(value: Decimal | None, y: dict) -> str | None:
    if value is None:
        return None
    if y["measure"] == "count" or y["agg"] == "count":
        return str(int(value))
    return _money(value)


def _label(key):
    """Group keys become JSON-friendly: dates turn into 'YYYY-MM-DD' strings."""
    return key.isoformat() if isinstance(key, date) else key


# --- table calculations -------------------------------------------------------
# They work on the aggregated chart values, not on rows (they are called "table calculations"), so they
# cost one pass over the buckets. A value is None where nothing can be said, never a made-up 0.


def running_total(values: list[Decimal | None]) -> list[Decimal]:
    """Cumulative sum in order. Only used on values that add up, so an empty bucket adds 0."""
    total, out = Decimal(0), []
    for value in values:
        total += value or 0
        out.append(total)
    return out


def moving_average(values: list[Decimal | None], window: int) -> list[Decimal | None]:
    """The mean of each value and the `window - 1` before it, skipping unknown values."""
    out = []
    for i in range(len(values)):
        known = [v for v in values[max(0, i - window + 1) : i + 1] if v is not None]
        out.append(sum(known, Decimal(0)) / len(known) if known else None)
    return out


def change(
    current: list[Decimal | None], prior: list[Decimal | None], as_: str
) -> list[Decimal | None]:
    """Each value minus its prior value, as an amount or as a % of the prior value.

    No percentage of nothing: a prior of 0 or None gives None.
    """
    out = []
    for now, before in zip(current, prior):
        if now is None or before is None:
            out.append(None)
        elif as_ == "amount":
            out.append(now - before)
        else:
            out.append((now - before) / abs(before) * 100 if before else None)
    return out


def share(value: Decimal | None, total: Decimal) -> Decimal | None:
    """`value` as a % of `total`; None when there is no total to take a share of."""
    return None if value is None or not total else value / total * 100


def _apply_calc(calc: dict, table: dict, x_keys: list, colors: list, granularity) -> dict:
    """The calculated value for every (x, colour) cell of `table`, in the same shape.

    % of total is the share of the chart's total for one series, or each segment's share of its
    own bar when the chart is split by colour (100% stacked: each bar is its own scope). The other
    calculations run along x, separately for each colour.
    """
    kind = calc["type"]
    if kind == "percent_of_total":
        if colors == [None]:
            total = sum((v for v in table.values() if v is not None), Decimal(0))
            return {key: share(value, total) for key, value in table.items()}
        bars = {x: sum((table[(x, c)] or 0 for c in colors), Decimal(0)) for x in x_keys}
        return {(x, c): share(value, bars[x]) for (x, c), value in table.items()}

    out = {}
    for c in colors:
        series = [table[(x, c)] for x in x_keys]
        if kind == "running_total":
            result = running_total(series)
        elif kind == "moving_average":
            result = moving_average(series, calc["window"])
        elif calc["vs"] == "previous":
            result = change(series, [None, *series[:-1]], calc["as"])
        else:
            by_bucket = dict(zip(x_keys, series))
            prior = [by_bucket.get(bucket_date(year_before(x), granularity)) for x in x_keys]
            result = change(series, prior, calc["as"])
        out.update({(x, c): value for x, value in zip(x_keys, result)})
    return out


def _fmt_cell(value: Decimal | None, y: dict, calc: dict | None) -> str | None:
    """Like _fmt, for a value that may have been through a table calculation."""
    if value is None or not calc:
        return _fmt(value, y)
    if calc["type"] == "percent_of_total" or calc.get("as") == "percent":
        return str(value.quantize(Decimal("0.1")))
    if calc["type"] == "moving_average":
        return _money(value)  # an average of counts has decimals too
    return _fmt(value, y)


def _balance_cells(book, x: dict, color: dict | None, span: tuple[date, date]) -> dict | None:
    """A balance per bucket or per source, or None if the chart splits it some other way.

    These cells come from the book and not from groups of rows: a source keeps its balance
    through a bucket where it has no rows, so every bucket has a value.
    """
    start, end = span
    keys = sorted(book.keys, key=lambda key: book.names.get(key, key or ""))
    if x["field"] == "date" and (not color or color["field"] == "data_source"):
        granularity = x["granularity"]
        days = [(k, _bucket_end(k, granularity, end)) for k in bucket_range(start, end, granularity)]
        if not color:
            return {(bucket,): book.at(last) for bucket, last in days}
        return {
            (bucket, book.names.get(key, key)): book.of(key, last)
            for bucket, last in days
            for key in keys
        }
    if x["field"] == "data_source" and not color:
        return {(book.names.get(key, key),): book.of(key, end) for key in keys}
    return None


def run_grouped(spec: dict, rows: list[dict], period: tuple[date, date]) -> dict:
    """bar / line / area / pie / donut: aggregate `y` for each value of `x` (and of `color`).

    `rows` must already be sorted by date (so `last` works). The result is "long" format,
    one output row per (x, color) pair; the frontend pivots it into chart series.
    """
    x, y = spec["x"], spec["y"]
    color = spec.get("color")
    x_dim = (x["field"], x.get("granularity"))
    dims = [x_dim] + ([(color["field"], None)] if color else [])

    span = (load_start(spec, period), period[1])  # the days the rows were loaded for
    book = current_view().book
    balances = _balance_cells(book, x, color, span) if y["measure"] == "balance" and book else None
    cells = balances
    if cells is None:
        cells = {
            key: _y_cell(group, y, group_span(dims, key, *span))
            for key, group in group_rows(rows, dims).items()
        }
    values = {key: value for key, value in cells.items() if value is not None}

    # "No data in this slot" is a true zero for totals, but unknown for an average or a max.
    foldable = y["agg"] in ("sum", "count")
    empty = Decimal(0) if foldable else None

    calc = spec.get("calc")
    if x["field"] == "date":
        # A calculation that looks back sees the earlier buckets too; only the period is shown.
        x_keys = bucket_range(load_start(spec, period), period[1], x["granularity"])
    elif x["field"] == "weekday":
        x_keys = list(range(7))
    elif x["field"] == "month_of_year":
        x_keys = list(range(1, 13))
    else:  # category / merchant / txn_type / data_source: rank the x values, keep the top few
        x_only = {key[0]: value for key, value in values.items()} if balances else {
            key[0]: _y_cell(group, y, group_span([x_dim], key, *span))
            for key, group in group_rows(rows, [x_dim]).items()
        }
        ranked = top_n(
            [(label, value) for label, value in x_only.items() if value is not None],
            spec.get("limit", 10),
            fold=foldable and not color,  # "Other" only makes sense for one series that adds up
        )
        x_keys = [label for label, _ in ranked]
        if spec.get("sort") == "label":
            x_keys.sort(key=lambda label: (label == OTHER_LABEL, label))  # "Other" stays last
        if not color:
            values = {(label,): value for label, value in ranked}

    colors = sorted({key[1] for key in values}, key=str) if color else [None]
    table = {
        (x_key, c): values.get((x_key, c) if color else (x_key,), empty)
        for x_key in x_keys
        for c in colors
    }
    if calc:
        table = _apply_calc(calc, table, x_keys, colors, x.get("granularity"))
    if x["field"] == "date":
        first = bucket_date(period[0], x["granularity"])
        x_keys = [x_key for x_key in x_keys if x_key >= first]

    out = []
    for x_key in x_keys:
        for color_key in colors:
            out.append(
                [_label(x_key)]
                + ([_label(color_key)] if color else [])
                + [_fmt_cell(table[(x_key, color_key)], y, calc)]
            )

    meta = {"chart": spec["chart"], "x": x, "y": y}
    if calc:
        meta["calc"] = calc
    return {
        "columns": ["x", "color", "value"] if color else ["x", "value"],
        "rows": out,
        "meta": meta,
    }


def _axis_keys(
    field: str,
    granularity: str | None,
    rows: list[dict],
    y: dict,
    spec: dict,
    period: tuple[date, date],
) -> list:
    """Every value one heatmap axis shows, in order: all the weekdays, all the months, every
    time bucket in the period, or the biggest categories (by total, or A to Z)."""
    if field == "date":
        return bucket_range(period[0], period[1], granularity)
    if field == "weekday":
        return list(range(7))
    if field == "month_of_year":
        return list(range(1, 13))
    totals = {key[0]: _y_cell(group, y) for key, group in group_rows(rows, [(field, None)]).items()}
    ranked = top_n(
        [(label, value) for label, value in totals.items() if value is not None],
        spec.get("limit", 10),
        fold=False,  # a cell for "everything else" would mix unlike things
    )
    keys = [label for label, _ in ranked]
    if spec.get("sort") == "label":
        keys.sort()
    return keys


def run_heatmap(spec: dict, rows: list[dict], period: tuple[date, date]) -> dict:
    """A matrix: one cell per (x, rows) pair, coloured by the measure.

    Cells with nothing in them are left out (blank), not drawn as zero. `axes` lists every
    x and row value in display order, so the frontend can place a cell and label an empty one.
    """
    x, y, row_field = spec["x"], spec["y"], spec["rows"]["field"]
    x_keys = _axis_keys(x["field"], x.get("granularity"), rows, y, spec, period)
    row_keys = _axis_keys(row_field, None, rows, y, spec, period)

    cells = {
        key: _y_cell(group, y)
        for key, group in group_rows(
            rows, [(x["field"], x.get("granularity")), (row_field, None)]
        ).items()
    }
    x_position = {key: n for n, key in enumerate(x_keys)}
    row_position = {key: n for n, key in enumerate(row_keys)}
    shown = [
        (x_position[x_key], row_position[row_key], x_key, row_key, value)
        for (x_key, row_key), value in cells.items()
        if value is not None and x_key in x_position and row_key in row_position
    ]
    shown.sort(key=lambda cell: cell[:2])  # left to right, then top to bottom
    return {
        "columns": ["x", "row", "value"],
        "rows": [
            [_label(x_key), _label(row_key), _fmt(value, y)]
            for _, _, x_key, row_key, value in shown
        ],
        "axes": {"x": [_label(k) for k in x_keys], "rows": [_label(k) for k in row_keys]},
        "meta": {"chart": "heatmap", "x": x, "rows": spec["rows"], "y": y},
    }


def run_calendar(spec: dict, rows: list[dict], period: tuple[date, date]) -> dict:
    """One value per day, for a calendar heatmap. Days with no transactions are left out."""
    start, end = period
    if (end - start).days + 1 > CALENDAR_MAX_DAYS:
        raise PeriodTooLong(f"A calendar shows at most {CALENDAR_MAX_DAYS} days.")
    y = spec["y"]
    cells = {
        key[0]: _y_cell(group, y) for key, group in group_rows(rows, [("date", "day")]).items()
    }
    return {
        "columns": ["x", "value"],
        "rows": [
            [day.isoformat(), _fmt(value, y)]
            for day, value in sorted(cells.items())
            if value is not None
        ],
        "meta": {"chart": "calendar", "y": y, "range": [start.isoformat(), end.isoformat()]},
    }


def _in_period(rows: list[dict], start: date, end: date) -> list[dict]:
    return [row for row in rows if start <= row["date"] <= end]


def previous_period(period: tuple[date, date]) -> tuple[date, date]:
    """The period of the same length that ends the day before `period` starts."""
    start, end = period
    length = (end - start).days + 1
    prev_end = start - timedelta(days=1)
    return prev_end - timedelta(days=length - 1), prev_end


def _or_zero(value: Decimal | None, y: dict) -> Decimal | None:
    """Nothing contributed: a real 0 for totals, still unknown for avg / min / max / median."""
    if value is None and y["agg"] in ("sum", "count"):
        return Decimal(0)
    return value


def _period_span(period: tuple[date, date]) -> Span:
    return Span(partial(days_in, *period), period[1])


def _baseline(rows: list[dict], periods: list[tuple[date, date]], y: dict) -> Decimal | None:
    """The number a KPI is compared with: its value in the one comparison period, or the mean of
    its values over several. A period with no rows counts as 0 for totals, and is skipped for
    averages, minimums and maximums (unknown, not zero)."""
    values = [_or_zero(_y_cell(_in_period(rows, *p), y, _period_span(p)), y) for p in periods]
    known =[value for value in values if value is not None]
    return sum(known, Decimal(0)) / len(known) if known else None


def _fmt_baseline(value: Decimal | None, y: dict, compare: str) -> str | None:
    """A mean of period counts has decimals ("12.5 transactions"); a single period's count doesn't."""
    if (
        value is not None
        and compare == "average"
        and (y["measure"] == "count" or y["agg"] == "count")
    ):
        return str(value.quantize(Decimal("0.1")))
    return _fmt(value, y)


def secondary_figures(
    ids: list[str],
    y: dict,
    rows: list[dict],
    value: Decimal | None,
    income_rows: list[dict],
) -> list[dict]:
    """The small figures under a KPI: how many transactions, the average and the biggest one,
    and the value as a share of income. `rows` are the period's rows after the panel's filters;
    `income_rows` are the period's rows with every filter but the type, so a spend KPI that
    only counts debits can still be set against income."""
    # A calculated field has no value per transaction: its figures describe the rows themselves.
    measure = "amount" if y["measure"] == FORMULA else y["measure"]
    amounts = [v for v in (measure_value(row, measure) for row in rows) if v is not None]
    figures = []
    for figure in ids:
        if figure == "count":
            result = str(len(amounts))
        elif figure == "average":
            result = _money(sum(amounts, Decimal(0)) / len(amounts)) if amounts else None
        elif figure == "largest":
            result = _money(max(amounts, key=abs)) if amounts else None
        else:  # share_of_income
            income = sum(
                (measure_value(row, "income") or Decimal(0) for row in income_rows), Decimal(0)
            )
            result = (
                str((value / income * 100).quantize(Decimal("0.1")))
                if value is not None and income
                else None
            )
        figures.append({"id": figure, "value": result})
    return figures


def run_kpi(
    spec: dict, rows: list[dict], period: tuple[date, date], all_types: list[dict] | None = None
) -> dict:
    """One headline number, with what it is compared with and the optional extras.

    Unlike the other runners this one receives rows from BEFORE the period too, and does its own
    filtering, because the comparison needs them. `all_types` is the same rows without the
    panel's type filter (None: `rows` already are), for the share of income.
    """
    y, kpi = spec["y"], spec["kpi"]
    current_rows = _in_period(rows, *period)
    current = _or_zero(_y_cell(current_rows, y, _period_span(period)), y)

    previous = change = None
    periods = comparison_periods(kpi, period)
    if periods:
        previous = _baseline(rows, periods, y)
        if current is not None and previous:  # skip None and 0: no percentage of nothing
            change = ((current - previous) / abs(previous) * 100).quantize(Decimal("0.1"))

    result = {
        "columns": ["value", "previous", "change_pct"],
        "rows": [
            [
                _fmt(current, y),
                _fmt_baseline(previous, y, kpi["compare"]),
                None if change is None else str(change),
            ]
        ],
        "meta": {"chart": "kpi", "y": y},
    }
    if kpi["sparkline"]:
        trend = {"chart": "line", "x": {"field": "date", "granularity": kpi["sparkline"]}, "y": y}
        grouped = run_grouped(trend, current_rows, period)
        result["sparkline"] = {
            "granularity": kpi["sparkline"],
            "columns": grouped["columns"],
            "rows": grouped["rows"],
        }
    if kpi["secondary"]:
        income_rows = _in_period(rows if all_types is None else all_types, *period)
        result["secondary"] = secondary_figures(
            kpi["secondary"], y, current_rows, current, income_rows
        )
    return result


def run_histogram(spec: dict, rows: list[dict]) -> dict:
    """Distribution of one measure, e.g. 'how big are my spends?'.

    The aggregation is ignored: a histogram counts individual rows, so each row's value is
    one data point.
    """
    y = spec["y"]
    values = [v for v in (measure_value(row, y["measure"]) for row in rows) if v is not None]
    return {
        "columns": ["start", "end", "count"],
        "rows": [
            [_money(start), _money(end), count]
            for start, end, count in histogram(values, spec.get("bins", 20))
        ],
        "meta": {"chart": "histogram", "y": y},
    }


def run(
    spec: dict,
    rows: list[dict],
    period: tuple[date, date],
    all_types: list[dict] | None = None,
    view: PanelView | None = None,
) -> dict:
    """The engine's one public entry point: a validated spec and plain rows in, a result out.

    `all_types` is only read by a KPI that shows its share of income (see run_kpi). `view` holds
    what balances and named data sources need besides the rows."""
    # A calculated field is worked out per group: parse its formula once.
    with parse_once(), panel_view(view):
        return _run(spec, rows, period, all_types)


def _run(spec: dict, rows: list[dict], period: tuple[date, date], all_types) -> dict:
    rows = sorted(rows, key=lambda row: row["date"])  # `last` and gap-filling rely on date order
    chart = spec["chart"]

    if chart == "kpi":
        return run_kpi(
            spec, rows, period, sorted(all_types, key=lambda r: r["date"]) if all_types else None
        )

    if chart in GROUPED_CHARTS:
        # Only the period's rows, plus any a table calculation looks back over.
        return run_grouped(spec, _in_period(rows, load_start(spec, period), period[1]), period)
    current = _in_period(rows, *period)  # rows from outside the period never reach a chart
    if chart == "heatmap":
        return run_heatmap(spec, current, period)
    if chart == "calendar":
        return run_calendar(spec, current, period)
    if chart == "histogram":
        return run_histogram(spec, current)
    raise ValueError(f"Unsupported chart: {chart!r}")  # "table" comes later

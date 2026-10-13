"""The chart engine: a validated spec and plain rows in, a small result out.

Pure Python: no Django, no database, no HTTP. Money is Decimal throughout and leaves the
engine as strings. Rows are dicts with the keys date, txn_type, category_name, amount, name
and balance, and the specs it reads are produced by `insights.spec.validate_spec`.
"""

from datetime import date, timedelta
from decimal import Decimal

GRANULARITIES = ("day", "week", "month", "quarter", "year")
MEASURES = ("spend", "income", "net", "amount", "count", "balance")
AGGS = ("sum", "avg", "min", "max", "median", "count", "last")
DIMENSIONS = ("date", "weekday", "month_of_year", "category", "txn_type", "merchant")
GROUPED_CHARTS = ("bar", "line", "area", "pie", "donut")

OTHER_LABEL = "Other"
# More time buckets than this is unreadable as a chart, and an unbounded range
# (say 2000 to 2100 by day) would let one request build a huge list.
MAX_BUCKETS = 1000


class TooManyBuckets(ValueError):
    """The period holds more time buckets than a chart can sensibly show."""


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


def _y_cell(rows: list[dict], y: dict) -> Decimal | None:
    """One aggregated number for a group of rows, or None if no row contributes.

    None means "nothing to show here", not zero: a Salary group has no *spend*, so it must
    not appear in a spend chart. Real zeros for empty time buckets are added later, where
    run_grouped fills the gaps.
    """
    values = []
    for row in rows:
        value = measure_value(row, y["measure"])
        if value is not None:
            values.append(value)
    if not values:
        return None
    return aggregate(values, y["agg"])


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


def run_grouped(spec: dict, rows: list[dict], period: tuple[date, date]) -> dict:
    """bar / line / area / pie / donut: aggregate `y` for each value of `x` (and of `color`).

    `rows` must already be sorted by date (so `last` works). The result is "long" format,
    one output row per (x, color) pair; the frontend pivots it into chart series.
    """
    x, y = spec["x"], spec["y"]
    color = spec.get("color")
    x_dim = (x["field"], x.get("granularity"))
    dims = [x_dim] + ([(color["field"], None)] if color else [])

    cells = {key: _y_cell(group, y) for key, group in group_rows(rows, dims).items()}
    values = {key: value for key, value in cells.items() if value is not None}

    # "No data in this slot" is a true zero for totals, but unknown for an average or a max.
    foldable = y["agg"] in ("sum", "count")
    empty = Decimal(0) if foldable else None

    if x["field"] == "date":
        x_keys = bucket_range(period[0], period[1], x["granularity"])
    elif x["field"] == "weekday":
        x_keys = list(range(7))
    elif x["field"] == "month_of_year":
        x_keys = list(range(1, 13))
    else:  # category / merchant / txn_type: rank the x values, keep the top few
        x_only = {key[0]: _y_cell(group, y) for key, group in group_rows(rows, [x_dim]).items()}
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

    out = []
    for x_key in x_keys:
        for color_key in colors:
            key = (x_key, color_key) if color else (x_key,)
            out.append(
                [_label(x_key)]
                + ([_label(color_key)] if color else [])
                + [_fmt(values.get(key, empty), y)]
            )

    return {
        "columns": ["x", "color", "value"] if color else ["x", "value"],
        "rows": out,
        "meta": {"chart": spec["chart"], "x": x, "y": y},
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


def run_kpi(spec: dict, rows: list[dict], period: tuple[date, date]) -> dict:
    """One headline number, plus the previous period's number and % change when spec["compare"].

    Unlike the other runners this one receives rows from BOTH periods and does its own
    filtering, because it needs the older rows for the comparison.
    """
    y = spec["y"]
    current = _or_zero(_y_cell(_in_period(rows, *period), y), y)

    previous = change = None
    if spec.get("compare"):
        previous = _or_zero(_y_cell(_in_period(rows, *previous_period(period)), y), y)
        if current is not None and previous:  # skip None and 0: no percentage of nothing
            change = ((current - previous) / abs(previous) * 100).quantize(Decimal("0.1"))

    return {
        "columns": ["value", "previous", "change_pct"],
        "rows": [[_fmt(current, y), _fmt(previous, y), None if change is None else str(change)]],
        "meta": {"chart": "kpi", "y": y},
    }


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


def run(spec: dict, rows: list[dict], period: tuple[date, date]) -> dict:
    """The engine's one public entry point: a validated spec and plain rows in, a result out."""
    rows = sorted(rows, key=lambda row: row["date"])  # `last` and gap-filling rely on date order
    chart = spec["chart"]

    if chart == "kpi":
        return run_kpi(spec, rows, period)

    current = _in_period(rows, *period)  # rows from outside the period never reach a chart
    if chart in GROUPED_CHARTS:
        return run_grouped(spec, current, period)
    if chart == "histogram":
        return run_histogram(spec, current)
    raise ValueError(f"Unsupported chart: {chart!r}")  # "table" comes later

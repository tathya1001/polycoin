"""Turns the model's PanelIntent into a validated panel spec, deterministically.

The model only describes the panel; code builds it. That splits the work three ways:
- Grounding: the user's words become their own category ids and a merchant filter.
- Safe fixes: a choice that cannot apply to the chart is dropped or replaced (a line chart with
  categories on x, a top N on a date axis), and each fix adds a note the user sees.
- Everything else goes to insights.spec.validate_spec, the same door a hand-made panel goes
  through. What it refuses (a pie of net, a running total without dates) raises SpecError, and
  the workflow asks the model to repair it rather than guessing.

`run_preview` then runs the spec like a dashboard would, with a few fixes for a period too big
to draw. `spec_to_intent` is the reverse of the compiler, for few-shot examples and tests.
"""

import copy
from dataclasses import dataclass, field
from datetime import date

from insights.engine import GRANULARITIES, GROUPED_CHARTS
from insights.services import run_queries
from insights.spec import (
    CHART_RULES,
    DEFAULT_WINDOW,
    MIN_DATE,
    SERIES_CHARTS,
    SpecError,
    allowed_aggs,
    default_agg,
    resolve_period,
    validate_date_filter,
    validate_spec,
)

from ..rag.periods import detect_period
from .context import AgentContext, MerchantMatch, match_merchant
from .errors import AgentError
from .schema import MAX_TITLE_LENGTH, PanelIntent

MAX_COARSEN = 2  # granularity steps the preview may take when a period has too many points
DEFAULT_LIMIT, DEFAULT_SORT = 10, "measure_desc"  # what validate_spec fills in

CHART_LABELS = {
    "kpi": "KPI", "bar": "Bar", "line": "Line", "area": "Area", "pie": "Pie", "donut": "Donut",
    "histogram": "Histogram", "calendar": "Calendar", "heatmap": "Heatmap",
}  # fmt: skip
MEASURE_LABELS = {
    "spend": "Spend", "income": "Income", "net": "Net", "amount": "Amount",
    "count": "Transactions", "balance": "Balance",
}  # fmt: skip
AGG_LABELS = {"avg": "Average", "min": "Smallest", "max": "Largest", "median": "Median"}
FIELD_LABELS = {
    "date": "date", "weekday": "weekday", "month_of_year": "month of year",
    "category": "category", "txn_type": "type", "merchant": "merchant",
    "data_source": "data source",
}  # fmt: skip
PERIOD_LABELS = {
    "this_month": "This month", "last_month": "Last month", "last_3_months": "Last 3 months",
    "last_12_months": "Last 12 months", "this_year": "This year", "all": "All time",
    "inherit": "Dashboard period",
}  # fmt: skip
MONEY_IN_ONLY, MONEY_OUT_ONLY = "income", "spend"


def _quoted(text: str) -> str:
    return f"“{text}”"


# --- grounding ------------------------------------------------------------------


@dataclass
class Grounding:
    """The user's words matched to their own data."""

    categories: list[str] = field(default_factory=list)  # category ids, for filters.categories
    data_sources: list[str] = field(default_factory=list)  # ids, for filters.data_sources
    merchant: str = ""  # for filters.merchant_contains
    notes: list[str] = field(default_factory=list)
    # A merchant no name matched, while a search index exists: the workflow may embed it and
    # call resolve_by_meaning. None when there is nothing left to try.
    pending_merchant: str | None = None


def _cached_match(value) -> MerchantMatch | None:
    return MerchantMatch(*value) if value else None


def ground(intent: PanelIntent, ctx: AgentContext, cache: dict | None = None) -> Grounding:
    """Match categories and the merchant. `cache` maps a lower-case merchant phrase to the
    stored match ([contains, how, matches], or None for "nothing matched"), so a follow-up on
    the same panel does not decrypt the merchant names again. It is updated in place."""
    cache = {} if cache is None else cache
    grounding = Grounding()

    for name in intent.categories:
        found = ctx.categories.match(name)
        if found is None:
            grounding.notes.append(f"No category matches {_quoted(name)}, so it was left out.")
            continue
        if found.category.id not in grounding.categories:
            grounding.categories.append(found.category.id)
        if found.how != "name":
            grounding.notes.append(
                f"{_quoted(name)} was read as the category {found.category.name}."
            )

    for name in intent.data_sources:
        source = ctx.sources.match(name)
        if source is None:
            grounding.notes.append(
                f"No data source matches {_quoted(name)}, so the panel shows all of them."
            )
            continue
        if source.id not in grounding.data_sources:
            grounding.data_sources.append(source.id)

    phrase = intent.merchant
    if phrase:
        key = phrase.lower()
        if key in cache:
            _apply_merchant(grounding, phrase, _cached_match(cache[key]))
        else:
            found = match_merchant(phrase, ctx.merchant_names())
            if found is None and ctx.embed:
                grounding.pending_merchant = phrase
            else:
                cache[key] = [found.contains, found.how, found.matches] if found else None
                _apply_merchant(grounding, phrase, found)
    return grounding


def resolve_by_meaning(
    grounding: Grounding, found: MerchantMatch | None, cache: dict | None = None
) -> Grounding:
    """Finish a pending merchant with what the search index found (or None)."""
    phrase = grounding.pending_merchant
    if phrase is None:
        return grounding
    if cache is not None:
        cache[phrase.lower()] = [found.contains, found.how, found.matches] if found else None
    grounding.pending_merchant = None
    _apply_merchant(grounding, phrase, found)
    return grounding


def _apply_merchant(grounding: Grounding, phrase: str, found: MerchantMatch | None) -> None:
    if found is None:
        grounding.notes.append(
            f"No merchant matches {_quoted(phrase)}, so the panel is not filtered by merchant."
        )
        return
    grounding.merchant = found.contains
    if found.how == "spelling":
        grounding.notes.append(f"{_quoted(phrase)} was read as the merchant {found.contains}.")
    elif found.how == "meaning":
        grounding.notes.append(
            f"{_quoted(phrase)} was matched by meaning to the merchant {found.contains}."
        )
    elif found.matches > 1:
        grounding.notes.append(f"{_quoted(phrase)} covers {found.matches} merchants.")


# --- the compiler -------------------------------------------------------------


@dataclass
class Compiled:
    spec: dict  # validated
    title: str
    notes: list[str]
    intent: PanelIntent  # with the period the panel really uses, for a follow-up to build on


def granularity_for(start: date, end: date) -> str:
    """A readable time step for the period: up to 45 days, 26 weeks or 36 months; quarters
    beyond that."""
    days = (end - start).days + 1
    if days <= 45:
        return "day"
    if days <= 183:
        return "week"
    if days <= 3 * 366:
        return "month"
    return "quarter"


def _date_filter(intent: PanelIntent, message: str, today: date, notes: list) -> tuple[dict, dict]:
    """(the panel's date filter, intent fields to update). A date phrase in the user's own
    message wins: code reads dates more reliably than a small model."""
    detected = detect_period(message, today) if message else None
    if detected:
        date_filter = detected.date_filter
        return date_filter, {
            "period": date_filter["preset"],
            "date_from": date_filter.get("from"),
            "date_to": date_filter.get("to"),
        }
    if intent.period is None:
        return {"preset": "inherit"}, {"date_from": None, "date_to": None}
    if intent.period == "custom":
        try:
            raw = {"preset": "custom", "from": intent.date_from, "to": intent.date_to}
            return validate_date_filter(raw), {}
        except SpecError:
            notes.append("The custom dates were not valid, so the panel uses the dashboard period.")
            return {"preset": "inherit"}, {"period": None, "date_from": None, "date_to": None}
    return {"preset": intent.period}, {"date_from": None, "date_to": None}


def _default_x(chart: str) -> str:
    allowed = CHART_RULES[chart]["x"]
    if chart == "heatmap":
        return "weekday"  # dates by day make a very wide grid
    return "date" if "date" in allowed else "category"


def _encoding(intent: PanelIntent, notes: list) -> dict:
    """chart, x, colour and rows, with the safe fixes."""
    chart = intent.chart or ("bar" if intent.x or intent.also_measures else "kpi")
    if intent.chart is None:
        notes.append(f"No chart type was given, so it is a {CHART_LABELS[chart].lower()} chart.")
    rules = CHART_RULES[chart]
    x, color = intent.x, intent.color

    if not rules["x"]:
        if x:
            notes.append(
                f"A {CHART_LABELS[chart].lower()} has no x axis, so {FIELD_LABELS[x]} was dropped."
            )
        x = None
    elif x is None:
        x = _default_x(chart)
        notes.append(f"No x axis was given, so it shows {FIELD_LABELS[x]}.")
    elif x not in rules["x"]:
        moved = x
        x = _default_x(chart)
        if rules["color"] and color is None:
            color = moved  # "a line of spend by category": dates along x, one line per category
            notes.append(
                f"A {chart} chart runs over dates, so {FIELD_LABELS[moved]} became the colour."
            )
        else:
            notes.append(
                f"A {chart} chart can't show {FIELD_LABELS[moved]} on the x axis, "
                f"so it shows {FIELD_LABELS[x]}."
            )

    encoding = {"chart": chart}
    if x:
        encoding["x"] = {"field": x}

    if color:
        if not rules["color"]:
            notes.append(
                f"A {CHART_LABELS[chart].lower()} can't be split by colour, so that was dropped."
            )
        elif color == x:
            notes.append("The colour was the same field as x, so it was dropped.")
        else:
            encoding["color"] = {"field": color}

    if chart == "heatmap":
        rows = intent.rows
        if rows is None or rows == x:
            rows = "category" if x != "category" else "weekday"
            notes.append(
                f"A heatmap needs a second field for its rows, so it uses {FIELD_LABELS[rows]}."
            )
        encoding["rows"] = {"field": rows}
    elif intent.rows:
        notes.append("Only a heatmap has rows, so that was dropped.")
    return encoding


def _measure(intent: PanelIntent, chart: str, notes: list) -> dict:
    measure = intent.measure or "spend"
    if intent.measure is None:
        notes.append("No measure was given, so it shows spend.")
    y = {"measure": measure}
    if chart == "histogram":
        return y  # a histogram plots single rows, so it has no aggregation
    agg = intent.agg
    if agg is not None and agg not in allowed_aggs(measure):
        notes.append(
            f"{AGG_LABELS.get(agg, agg).capitalize()} does not apply to "
            f"{MEASURE_LABELS[measure].lower()}, so it uses {default_agg(measure)}."
        )
        agg = None
    y["agg"] = agg or default_agg(measure)
    return y


def _also(intent: PanelIntent, encoding: dict, notes: list) -> list[dict]:
    """The measures shown beside the first one. Only some charts can show several."""
    first = encoding["y"]["measure"]
    wanted = [name for name in dict.fromkeys(intent.also_measures) if name != first]
    if not wanted:
        return []
    chart = encoding["chart"]
    if chart not in SERIES_CHARTS:
        names = " and ".join(MEASURE_LABELS[name].lower() for name in wanted)
        notes.append(f"A {CHART_LABELS[chart].lower()} shows one measure, so {names} was left out.")
        return []
    return [{"measure": name, "agg": default_agg(name)} for name in wanted]


def _txn_type(intent: PanelIntent, measures: list[str], notes: list) -> str | None:
    """A type filter that would leave a measure empty is dropped."""
    kind = intent.txn_type
    if len(measures) > 1:
        if kind:
            notes.append("This chart compares measures, so the type filter was dropped.")
        return None
    measure = measures[0]
    if (measure == MONEY_OUT_ONLY and kind == "credit") or (
        measure == MONEY_IN_ONLY and kind == "debit"
    ):
        notes.append(
            f"{MEASURE_LABELS[measure]} already picks its own type, so the type filter was dropped."
        )
        return None
    return kind


def _options(intent: PanelIntent, encoding: dict, notes: list) -> dict:
    """Top N, sort, the KPI options and the table calculation."""
    chart, options = encoding["chart"], {}
    categorical = encoding.get("x", {}).get("field") not in (None, "date")
    if intent.limit is not None or intent.sort is not None:
        if categorical:
            if intent.limit is not None:
                options["limit"] = intent.limit
            if intent.sort is not None:
                options["sort"] = intent.sort
        else:
            notes.append("Top N and sorting only apply when x is not a date, so they were dropped.")

    if chart == "kpi":
        compare = intent.compare or "none"
        kpi = {"compare": compare}
        if compare == "average" and intent.average_of is not None:
            kpi["average_of"] = intent.average_of
        if intent.direction is not None:
            kpi["direction"] = intent.direction
        options["kpi"] = kpi
    elif intent.compare not in (None, "none"):
        notes.append("Comparisons only apply to KPI cards, so it was dropped.")

    if intent.calc:
        if chart not in GROUPED_CHARTS:
            notes.append(f"A {CHART_LABELS[chart].lower()} has no calculations, so it was dropped.")
        else:
            calc = {"type": intent.calc}
            if intent.calc == "moving_average":
                calc["window"] = intent.window or DEFAULT_WINDOW
            if intent.calc == "change":
                calc["vs"] = intent.change_vs or "previous"
                calc["as"] = intent.change_as or "percent"
            options["calc"] = calc
    return options


def compile_intent(
    intent: PanelIntent,
    grounding: Grounding,
    ctx: AgentContext,
    *,
    message: str = "",
    dashboard_date: dict | None = None,
) -> Compiled:
    """The panel spec for a "panel" intent. Raises SpecError for what only the model can fix.

    `message` is the user's latest message (its date phrase wins); `dashboard_date` is the
    dashboard's validated date filter, for the period an inheriting panel will show."""
    if intent.kind != "panel":
        raise ValueError("Only a panel intent compiles to a spec.")
    notes = list(grounding.notes)
    date_filter, period_update = _date_filter(intent, message, ctx.today, notes)

    encoding = _encoding(intent, notes)
    chart = encoding["chart"]
    encoding["y"] = _measure(intent, chart, notes)
    also = _also(intent, encoding, notes)

    if encoding.get("x", {}).get("field") == "date":
        granularity = intent.granularity
        if granularity is None:
            start, end = resolve_period(
                date_filter, dashboard_date or {"preset": "inherit"}, ctx.today
            )
            if start == MIN_DATE:  # "all" starts at the user's first transaction
                start = min(ctx.first_date, end) if ctx.first_date else end
            granularity = granularity_for(start, end)
        encoding["x"]["granularity"] = granularity

    raw = {
        **encoding,
        **_options(intent, encoding, notes),
        "also": also,
        "filters": {
            "date": date_filter,
            "type": _txn_type(
                intent, [encoding["y"]["measure"], *(item["measure"] for item in also)], notes
            ),
            "categories": grounding.categories,
            "data_sources": grounding.data_sources,
            "merchant_contains": grounding.merchant,
        },
    }
    spec = validate_spec(raw)
    return Compiled(
        spec=spec,
        title=intent.title or describe(spec),
        notes=notes,
        intent=intent.model_copy(update=period_update),
    )


# --- describing a spec ----------------------------------------------------------


def _period_label(date_filter: dict) -> str:
    if date_filter["preset"] == "custom":
        start, end = date.fromisoformat(date_filter["from"]), date.fromisoformat(date_filter["to"])
        return f"{start.day} {start:%b %Y} – {end.day} {end:%b %Y}"
    return PERIOD_LABELS[date_filter["preset"]]


def describe(spec: dict) -> str:
    """A one-line summary built from the spec: "Spend by category · Last 3 months · Bar"."""
    y = spec["y"]
    what = MEASURE_LABELS[y["measure"]]
    if spec["chart"] != "histogram" and y["agg"] in AGG_LABELS:
        what = f"{AGG_LABELS[y['agg']]} {what.lower()}"
    for item in spec.get("also", ()):
        what += f" and {MEASURE_LABELS[item['measure']].lower()}"
    split =[spec[key]["field"] for key in ("x", "color", "rows") if key in spec]
    if split:
        what += " by " + " and ".join(FIELD_LABELS[name] for name in split)
    parts = [what, _period_label(spec["filters"]["date"]), CHART_LABELS[spec["chart"]]]
    return " · ".join(parts)[:MAX_TITLE_LENGTH]


# --- the preview ----------------------------------------------------------------


@dataclass
class Preview:
    spec: dict  # as previewed, after any fixes
    result: dict | None
    notes: list[str]
    error: dict | None = None  # {"code", "detail"}
    repairable: bool = False  # the model may be able to fix the error


def run_preview(user, spec: dict, dashboard: dict, today: date, notes: list) -> Preview:
    """Run the panel as the dashboard would. `dashboard` is {"filters", "parameters"}.

    Too many points: coarser granularity, up to MAX_COARSEN steps. A calendar over a year: the
    last 12 months. Too many rows is final: no model can fix the size of the user's data. Any
    other error goes back to the model. Raises AgentError("invalid_filters") for a bad
    dashboard filter, which is the browser's mistake, not the panel's.
    """
    spec, notes, coarsened = copy.deepcopy(spec), list(notes), 0
    while True:
        try:
            result = run_queries(
                user,
                dashboard.get("filters"),
                [{"key": "preview", "spec": spec}],
                today=today,
                parameters=dashboard.get("parameters"),
            )["preview"]
        except SpecError as problem:
            raise AgentError("invalid_filters", problem.detail) from None
        error = result.get("error")
        if error is None:
            return Preview(spec, result, notes)

        x = spec.get("x", {})
        step = GRANULARITIES.index(x["granularity"]) if x.get("field") == "date" else None
        if (
            error["code"] == "too_many_points"
            and step is not None
            and step + 1 < len(GRANULARITIES)
            and coarsened < MAX_COARSEN
        ):
            x["granularity"] = GRANULARITIES[step + 1]
            coarsened += 1
            notes.append(f"The period had too many points, so it is grouped by {x['granularity']}.")
            continue
        if (
            error["code"] == "period_too_long"
            and spec["chart"] == "calendar"
            and spec["filters"]["date"] != {"preset": "last_12_months"}
        ):
            spec["filters"]["date"] = {"preset": "last_12_months"}
            notes.append("A calendar shows at most a year, so it shows the last 12 months.")
            continue
        return Preview(spec, None, notes, error, repairable=error["code"] != "too_many_rows")


# --- the reverse: spec to intent --------------------------------------------------


def spec_to_intent(
    spec: dict,
    category_names: dict | None = None,
    title: str | None = None,
    source_names: dict | None = None,
) -> PanelIntent:
    """The intent that compiles back to `spec` (presentation fields aside). Values equal to the
    validator's defaults are left unset, as the model is asked to do. `category_names` and
    `source_names` map ids to names; ids they do not know are left out."""
    spec = validate_spec(spec)
    if spec["chart"] == "text":
        raise ValueError("A text panel has no intent.")
    y, filters = spec["y"], spec["filters"]
    date_filter = filters["date"]
    categorical = spec.get("x", {}).get("field") not in (None, "date")
    kpi, calc = spec.get("kpi", {}), spec.get("calc", {})
    names = category_names or {}
    fields = {
        "kind": "panel",
        "title": title,
        "chart": spec["chart"],
        "measure": y["measure"],
        "also_measures": [item["measure"] for item in spec.get("also", ())],
        "agg": y["agg"]
        if spec["chart"] != "histogram" and y["agg"] != default_agg(y["measure"])
        else None,
        "x": spec.get("x", {}).get("field"),
        "granularity": spec.get("x", {}).get("granularity"),
        "color": spec.get("color", {}).get("field"),
        "rows": spec.get("rows", {}).get("field"),
        "period": None if date_filter["preset"] == "inherit" else date_filter["preset"],
        "date_from": date_filter.get("from"),
        "date_to": date_filter.get("to"),
        "categories": [names[pk] for pk in filters["categories"] if pk in names],
        "data_sources": [
            (source_names or {})[pk]
            for pk in filters["data_sources"]
            if pk in (source_names or {})
        ],
        "merchant": filters["merchant_contains"] or None,
        "txn_type": filters["type"],
        "limit": spec["limit"] if categorical and spec["limit"] != DEFAULT_LIMIT else None,
        "sort": spec["sort"] if categorical and spec["sort"] != DEFAULT_SORT else None,
        "compare": kpi.get("compare") if kpi.get("compare") != "none" else None,
        "direction": kpi.get("direction") if kpi.get("direction") != "auto" else None,
        "average_of": kpi.get("average_of"),
        "calc": calc.get("type"),
        "window": calc.get("window"),
        "change_vs": calc.get("vs"),
        "change_as": calc.get("as"),
    }
    return PanelIntent(**fields)

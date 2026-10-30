"""Validation for panel specs: the only door between JSON from the browser and the engine.

`validate_spec` whitelists every key and value, fills in defaults, and returns the clean
shape the engine reads. Saved panel configs go through it on the way in AND on the way out,
so a config written by an older version can never reach the engine unchecked.
"""

import copy
import uuid
from datetime import date, timedelta

from categories.colors import is_hex_color

from .engine import DIMENSIONS, GRANULARITIES, GROUPED_CHARTS, MEASURES, add_months
from .formula import (
    FORMULA,
    RESULT_FORMS,
    FormulaError,
    compile_expression,
    language,
    tidy,
)
from .formula import (
    MAX_LENGTH as FORMULA_MAX_LENGTH,
)

# Bumped whenever the shape of a spec changes; `upgrade` brings older saved specs forward one
# version at a time, so a panel saved by any earlier version keeps working unchanged.
SPEC_VERSION = 9

CATEGORICAL = tuple(dimension for dimension in DIMENSIONS if dimension != "date")
CHARTS = (
    "kpi", "bar", "line", "area", "pie", "donut", "histogram", "calendar", "heatmap", "text",
)  # fmt: skip
SORTS = ("measure_desc", "label")
ORIENTATIONS = ("vertical", "horizontal")
TXN_TYPES = ("credit", "debit")
SPEC_KEYS = (
    "v", "chart", "x", "y", "color", "sort", "limit", "bins", "rows", "kpi", "calc", "format", "bind",
    "stacked", "orientation", "series_colors", "filters",
)  # fmt: skip

DATE_PRESETS = (
    "this_month", "last_month", "last_3_months", "last_12_months", "this_year", "all", "custom",
)  # fmt: skip
DEFAULT_PRESET = "last_3_months"  # used when neither the panel nor the dashboard picks one
MIN_DATE = date(2000, 1, 1)
MAX_DATE = date(2100, 12, 31)
MAX_CATEGORIES = 20
MAX_DATA_SOURCES = 20  # keep equal to datasources.models.MAX_SOURCES_PER_USER
MAX_MERCHANT_LENGTH = 60
LIMIT_RANGE = (1, 50)  # how many x values a bar or pie keeps before folding the rest
BINS_RANGE = (5, 50)
MAX_SERIES_COLORS = 50  # colour overrides one panel may carry
MAX_SERIES_KEY_LENGTH = 100  # a category name, "credit", a merchant...

# Table calculations: computed on the aggregated chart values, after the buckets are filled.
CALCS = ("running_total", "percent_of_total", "moving_average", "change")
TIME_CALCS = ("running_total", "moving_average", "change")  # these need dates on the x axis
ADDITIVE_CALCS = ("running_total", "percent_of_total")  # these need values that add up
CHANGE_VS = ("previous", "year_ago")
CHANGE_AS = ("percent", "amount")
WINDOW_RANGE = (2, 12)  # buckets in a moving average
DEFAULT_WINDOW = 3

# KPI cards: what the number is compared with, how a change is coloured, and the small extras.
KPI_COMPARES = ("none", "previous", "year_ago", "average")
AVERAGE_OF_RANGE = (3, 12)  # periods averaged by the "average" comparison
DEFAULT_AVERAGE_OF = 3
DIRECTIONS = ("auto", "up_is_good", "down_is_good")
SECONDARY = ("count", "average", "largest", "share_of_income")
MAX_SECONDARY = 3
AMOUNT_MEASURES = ("spend", "income", "net", "amount")  # measures that are sums of money

# A calculated field is a measure the user writes as a formula (see formula.py).
FORMULA_CHARTS = ("bar", "line", "area", "kpi")

# Presentation only: the engine never reads these, so they can't change a chart's numbers.
NUMBER_FORMATS = ("auto", "full", "compact")  # auto: compact on axes, full in tooltips
LEGENDS = ("auto", "top", "bottom", "right", "none")  # auto: the chart's own default
FORMAT_CHARTS = ("bar", "line", "area", "pie", "donut", "histogram", "calendar", "heatmap")
LEGEND_CHARTS = ("bar", "line", "area", "pie", "donut")
AXIS_CHARTS = ("bar", "line", "area")
MAX_AXIS_VALUE = 1e12

MAX_TEXT_LENGTH = 2000  # characters in a text panel
CALENDAR_MAX_DAYS = 366  # a calendar heatmap shows at most a year of days

# Dashboard parameters: a few values the whole dashboard shares. A panel follows one only where
# it is bound to it (`bind`); an unbound field keeps its own value.
PARAMETER_DEFAULTS = {
    "top_n": 10,
    "granularity": "month",
    "measure": "spend",
    "comparison": "previous",
}
PARAMETER_MEASURES = ("spend", "income", "net")
PARAMETER_COMPARISONS = ("previous", "year_ago")
# panel field -> the parameter that may drive it
BINDINGS = {
    "limit": "top_n",  # how many bars, slices or cells a categorical chart keeps
    "granularity": "granularity",  # the time step of a date axis
    "measure": "measure",
    "compare": "comparison",  # what a KPI is compared with
    "vs": "comparison",  # what a change calculation is measured against
}

# Which fields each chart may use for x, and whether it may split into a colour series.
# Served to the frontend through catalogue(), so the editor can grey out invalid combinations.
CHART_RULES = {
    "kpi": {"x": (), "color": False},
    "bar": {"x": ("date", *CATEGORICAL), "color": True},
    "line": {"x": ("date",), "color": True},
    "area": {"x": ("date",), "color": True},
    "pie": {"x": CATEGORICAL, "color": False},
    "donut": {"x": CATEGORICAL, "color": False},
    "histogram": {"x": (), "color": False},
    "calendar": {"x": (), "color": False},  # one cell per day, so it has no axis to pick
    "heatmap": {"x": ("date", *CATEGORICAL), "color": False},  # needs `rows` as well
    "text": {"x": (), "color": False},  # a note on the dashboard: no data, no fields
}


class SpecError(Exception):
    """A rejected panel spec. Same {code, detail} idea as ImportProblem."""

    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


# --- small helpers ------------------------------------------------------------


def _bad(detail: str) -> SpecError:
    return SpecError("invalid_spec", detail)


def _default(value, default):
    """Browsers send null for 'not set'; treat it like a missing key."""
    return default if value is None else value


def _only_keys(data, allowed: tuple, field: str) -> None:
    """`data` must be an object that uses only the `allowed` keys."""
    if not isinstance(data, dict):
        raise _bad(f"{field} must be an object.")
    unknown = set(data) - set(allowed)
    if unknown:
        raise _bad(f"Unknown keys in {field}: {', '.join(sorted(unknown))}.")


def _choice(value, allowed, field: str):
    if value not in allowed:
        raise _bad(f"{field} must be one of: {', '.join(map(str, allowed))}.")
    return value


def _int_in_range(value, low: int, high: int, field: str, default: int) -> int:
    value = _default(value, default)
    # bool is a subclass of int in Python, so True would otherwise pass as 1
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise _bad(f"{field} must be a whole number from {low} to {high}.")
    return value


def _bool(value, field: str, default: bool = False) -> bool:
    value = _default(value, default)
    if not isinstance(value, bool):
        raise _bad(f"{field} must be true or false.")
    return value


def _parse_date(value, field: str) -> date:
    if not isinstance(value, str) or len(value) != 10:
        raise _bad(f"{field} must be a date like 2026-10-31.")
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise _bad(f"{field} must be a real date like 2026-10-31.") from None
    if not MIN_DATE <= parsed <= MAX_DATE:
        raise _bad(f"{field} must be between {MIN_DATE} and {MAX_DATE}.")
    return parsed


# --- chart rules --------------------------------------------------------------


def allowed_aggs(measure: str) -> tuple:
    """Not every aggregation makes sense for every measure."""
    if measure == "balance":
        return ("last",)  # a balance is a snapshot: add or average them and it's meaningless
    if measure == "count":
        return ("sum",)  # the 'count' measure is already 1 per row, so summing counts rows
    if measure == FORMULA:
        # A formula is worked out once per group, so there is nothing to choose. "avg" is stored
        # because it keeps off what only makes sense for values that add up (a running total, a
        # share of the total, folding the rest into "Other") and leaves an empty bucket empty.
        return ("avg",)
    return ("sum", "avg", "min", "max", "median")


def default_agg(measure: str) -> str:
    return allowed_aggs(measure)[0]


def validate_formula(raw) -> dict:
    """The calculated field behind a `formula` measure: its text, and how the result is shown."""
    _only_keys(raw, ("expression", "as"), "y.formula")
    expression = raw.get("expression")
    if not isinstance(expression, str):
        raise _bad("y.formula.expression must be text.")
    expression = tidy(expression)  # spaces inside quoted text are part of the text
    try:
        compile_expression(expression)
    except FormulaError as problem:
        raise _bad(f"Formula: {problem}") from None
    return {
        "expression": expression,
        "as": _choice(_default(raw.get("as"), "number"), RESULT_FORMS, "y.formula.as"),
    }


def validate_encoding(raw: dict) -> dict:
    """Check the parts of a spec that decide what the chart shows, and fill in defaults.

    Returns the clean version in the shape the engine reads. Raises SpecError.
    """
    if not isinstance(raw, dict):
        raise _bad("The spec must be an object.")
    chart = _choice(raw.get("chart"), CHARTS, "chart")
    rules = CHART_RULES[chart]
    spec = {"chart": chart}

    # --- x axis ---
    x_raw = raw.get("x")
    if not rules["x"]:
        if x_raw is not None:
            raise _bad(f"A {chart} chart has no x axis.")
    else:
        _only_keys(x_raw, ("field", "granularity"), "x")
        field = _choice(x_raw.get("field"), rules["x"], "x.field")
        if field == "date":
            granularity = _choice(x_raw.get("granularity"), GRANULARITIES, "x.granularity")
            spec["x"] = {"field": field, "granularity": granularity}
        elif x_raw.get("granularity") is not None:
            raise _bad("Only the date field has a granularity.")
        else:
            spec["x"] = {"field": field}

    # --- y: measure + aggregation ---
    y_raw = raw.get("y")
    _only_keys(y_raw, ("measure", "agg", "formula"), "y")
    measure = _choice(y_raw.get("measure"), (*MEASURES, FORMULA), "y.measure")
    if measure == FORMULA and chart not in FORMULA_CHARTS:
        raise _bad(f"A calculated field works on {', '.join(FORMULA_CHARTS)} panels, not {chart}.")
    if chart in ("pie", "donut") and measure in ("net", "balance"):
        raise _bad("A pie or donut needs a measure that is never negative (not net or balance).")
    if chart == "histogram":
        if measure == "count":
            raise _bad("A histogram needs amounts, not counts.")
        agg = default_agg(measure)  # a histogram plots single rows, so the aggregation is unused
    else:
        agg = _choice(
            _default(y_raw.get("agg"), default_agg(measure)), allowed_aggs(measure), "y.agg"
        )
    spec["y"] = {"measure": measure, "agg": agg}
    if measure == FORMULA:
        spec["y"]["formula"] = validate_formula(y_raw.get("formula"))
    elif y_raw.get("formula") is not None:
        raise _bad("Only a calculated field has a formula.")

    # --- rows: the second axis of a matrix heatmap ---
    rows_raw = raw.get("rows")
    if chart == "heatmap":
        _only_keys(rows_raw, ("field",), "rows")
        rows_field = _choice(rows_raw.get("field"), CATEGORICAL, "rows.field")
        if rows_field == spec["x"]["field"]:
            raise _bad("Rows must be a different field from x.")
        spec["rows"] = {"field": rows_field}
    elif rows_raw is not None:
        raise _bad(f"A {chart} chart has no rows field.")

    # --- colour: a second dimension that splits each x value into several series ---
    color_raw = raw.get("color")
    if color_raw is not None:
        if not rules["color"]:
            raise _bad(f"A {chart} chart can't be split by colour.")
        _only_keys(color_raw, ("field",), "color")
        color_field = _choice(color_raw.get("field"), CATEGORICAL, "color.field")
        if color_field == spec["x"]["field"]:
            raise _bad("Colour must be a different field from x.")
        spec["color"] = {"field": color_field}

    # --- options ---
    spec["sort"] = _choice(_default(raw.get("sort"), "measure_desc"), SORTS, "sort")
    spec["limit"] = _int_in_range(raw.get("limit"), *LIMIT_RANGE, "limit", 10)
    spec["bins"] = _int_in_range(raw.get("bins"), *BINS_RANGE, "bins", 20)
    return spec


def validate_calc(raw, spec: dict) -> dict | None:
    """A table calculation for a grouped chart, or None. `spec` is the validated encoding."""
    raw = _default(raw, None)
    if raw is None:
        return None
    _only_keys(raw, ("type", "window", "vs", "as"), "calc")
    kind = _choice(raw.get("type"), CALCS, "calc.type")
    chart = spec["chart"]
    if chart not in GROUPED_CHARTS:
        raise _bad(f"A {chart} panel has no calculations.")
    if kind in TIME_CALCS and spec.get("x", {}).get("field") != "date":
        raise _bad("A running total, moving average or change needs dates on the x axis.")
    if kind in ADDITIVE_CALCS and spec["y"]["agg"] not in ("sum", "count"):
        raise _bad("A running total or % of total needs values that add up (a sum or a count).")
    if kind == "percent_of_total" and spec["y"]["measure"] in ("net", "balance"):
        raise _bad("% of total needs a measure that is never negative (not net or balance).")

    calc = {"type": kind}
    if kind == "moving_average":
        calc["window"] = _int_in_range(
            raw.get("window"), *WINDOW_RANGE, "calc.window", DEFAULT_WINDOW
        )
    elif raw.get("window") is not None:
        raise _bad("Only a moving average has a window.")
    if kind == "change":
        calc["vs"] = _choice(_default(raw.get("vs"), "previous"), CHANGE_VS, "calc.vs")
        calc["as"] = _choice(_default(raw.get("as"), "percent"), CHANGE_AS, "calc.as")
    elif raw.get("vs") is not None or raw.get("as") is not None:
        raise _bad("Only a change has vs and as.")
    return calc


def _validate_secondary(raw, y: dict) -> list:
    """The small figures under a KPI's number: unique, at most MAX_SECONDARY, each valid for `y`."""
    raw = _default(raw, [])
    if not isinstance(raw, list) or len(raw) > MAX_SECONDARY:
        raise _bad(f"kpi.secondary must be a list of at most {MAX_SECONDARY} figures.")
    for figure in raw:
        _choice(figure, SECONDARY, "kpi.secondary")
        if raw.count(figure) > 1:
            raise _bad(f"kpi.secondary lists {figure} twice.")
        if figure != "count" and y["measure"] not in AMOUNT_MEASURES:
            raise _bad(f"The {figure} figure needs a money measure (spend, income, net or amount).")
        if figure == "share_of_income" and y["agg"] != "sum":
            raise _bad("The share of income needs the sum aggregation.")
    return list(raw)


def validate_kpi(raw, spec: dict) -> dict | None:
    """The KPI card's options, or None for any other chart. `spec` is the validated encoding."""
    raw = _default(raw, None)
    if spec["chart"] != "kpi":
        if raw is not None:
            raise _bad(f"A {spec['chart']} panel has no KPI options.")
        return None
    raw = _default(raw, {})
    _only_keys(raw, ("compare", "average_of", "sparkline", "direction", "secondary"), "kpi")

    compare = _choice(_default(raw.get("compare"), "none"), KPI_COMPARES, "kpi.compare")
    kpi = {"compare": compare}
    if compare == "average":
        kpi["average_of"] = _int_in_range(
            raw.get("average_of"), *AVERAGE_OF_RANGE, "kpi.average_of", DEFAULT_AVERAGE_OF
        )
    elif raw.get("average_of") is not None:
        raise _bad("Only the average comparison has average_of.")

    sparkline = raw.get("sparkline")
    if sparkline is not None:
        _choice(sparkline, GRANULARITIES, "kpi.sparkline")
    kpi["sparkline"] = sparkline
    kpi["direction"] = _choice(_default(raw.get("direction"), "auto"), DIRECTIONS, "kpi.direction")
    kpi["secondary"] = _validate_secondary(raw.get("secondary"), spec["y"])
    return kpi


def _number(value, field: str):
    """A finite number (not a bool), or None."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _bad(f"{field} must be a number.")
    if not abs(value) <= MAX_AXIS_VALUE:  # also false for NaN
        raise _bad(f"{field} must be between -{MAX_AXIS_VALUE:g} and {MAX_AXIS_VALUE:g}.")
    return value


def validate_format(raw, spec: dict) -> dict | None:
    """Labels, number style, legend and value-axis bounds, or None for charts without them."""
    raw = _default(raw, None)
    chart = spec["chart"]
    if chart not in FORMAT_CHARTS:
        if raw is not None:
            raise _bad(f"A {chart} panel has no formatting options.")
        return None
    raw = _default(raw, {})
    _only_keys(raw, ("labels", "number", "legend", "axis"), "format")

    fmt = {
        "labels": _bool(raw.get("labels"), "format.labels"),
        "number": _choice(_default(raw.get("number"), "auto"), NUMBER_FORMATS, "format.number"),
        "legend": _choice(_default(raw.get("legend"), "auto"), LEGENDS, "format.legend"),
    }
    if fmt["legend"] != "auto" and chart not in LEGEND_CHARTS:
        raise _bad(f"A {chart} chart has no legend to place.")

    axis_raw = _default(raw.get("axis"), {})
    _only_keys(axis_raw, ("min", "max"), "format.axis")
    axis = {bound: _number(axis_raw.get(bound), f"format.axis.{bound}") for bound in ("min", "max")}
    if any(value is not None for value in axis.values()) and chart not in AXIS_CHARTS:
        raise _bad(f"A {chart} chart has no value axis to bound.")
    if None not in axis.values() and axis["min"] >= axis["max"]:
        raise _bad("format.axis.min must be below format.axis.max.")
    fmt["axis"] = axis
    return fmt


def validate_text(raw: dict) -> dict:
    """A text panel: just its words. They are only ever shown as text, never run or fetched."""
    _only_keys(raw, ("v", "chart", "text"), "spec")
    words = _default(raw.get("text"), "")
    if not isinstance(words, str) or len(words) > MAX_TEXT_LENGTH:
        raise _bad(f"text must be words of at most {MAX_TEXT_LENGTH} characters.")
    return {"v": SPEC_VERSION, "chart": "text", "text": words.replace("\r\n", "\n")}


def validate_parameters(raw) -> dict:
    """The dashboard's parameter values, with every missing one at its default."""
    raw = _default(raw, {})
    _only_keys(raw, tuple(PARAMETER_DEFAULTS), "parameters")
    defaults = PARAMETER_DEFAULTS
    return {
        "top_n": _int_in_range(
            raw.get("top_n"), *LIMIT_RANGE, "parameters.top_n", defaults["top_n"]
        ),
        "granularity": _choice(
            _default(raw.get("granularity"), defaults["granularity"]),
            GRANULARITIES,
            "parameters.granularity",
        ),
        "measure": _choice(
            _default(raw.get("measure"), defaults["measure"]),
            PARAMETER_MEASURES,
            "parameters.measure",
        ),
        "comparison": _choice(
            _default(raw.get("comparison"), defaults["comparison"]),
            PARAMETER_COMPARISONS,
            "parameters.comparison",
        ),
    }


def _bindable(field: str, spec: dict) -> bool:
    """Whether this panel has the field that `field` would drive."""
    chart = spec["chart"]
    if field == "limit":
        return chart in ("bar", "pie", "donut", "heatmap")
    if field == "granularity":
        return spec.get("x", {}).get("field") == "date"
    if field == "measure":
        return spec["y"]["measure"] != FORMULA  # a formula is the panel's own
    if field == "compare":
        return chart == "kpi"
    return spec.get("calc", {}).get("type") == "change"  # vs


def validate_bind(raw, spec: dict) -> dict | None:
    """Which fields of this panel follow a dashboard parameter: {field: parameter}, or None."""
    raw = _default(raw, None)
    if raw is None:
        return None
    _only_keys(raw, tuple(BINDINGS), "bind")
    for field, parameter in raw.items():
        if parameter != BINDINGS[field]:
            raise _bad(f"bind.{field} can only follow the {BINDINGS[field]} parameter.")
        if not _bindable(field, spec):
            raise _bad(f"This panel has no {field} to follow a parameter.")
    return {field: raw[field] for field in BINDINGS if field in raw} or None


def apply_parameters(spec: dict, parameters: dict) -> dict:
    """The spec with each bound field set from the dashboard's parameters, validated again.

    A value can fit the dashboard but not one panel (a pie can't show "net"); that panel then
    gets its own error, and the rest of the dashboard is unaffected. `bind` is gone from the
    result: it is the resolved spec the engine runs.
    """
    bind = spec.get("bind")
    if not bind:
        return spec
    raw = copy.deepcopy({key: value for key, value in spec.items() if key != "bind"})
    for field in bind:
        value = parameters[BINDINGS[field]]
        if field == "limit":
            raw["limit"] = value
        elif field == "granularity":
            raw["x"]["granularity"] = value
        elif field == "measure":
            raw["y"]["measure"] = value
            if raw["y"]["agg"] not in allowed_aggs(value):
                raw["y"]["agg"] = default_agg(value)  # "last" belongs to balance alone
        elif field == "compare":
            raw["kpi"]["compare"] = value
            raw["kpi"].pop("average_of", None)  # only the average comparison has it
        else:
            raw["calc"]["vs"] = value
    try:
        return validate_spec(raw)
    except SpecError as problem:
        raise SpecError(
            "parameter_conflict",
            f"The dashboard's parameters don't fit this panel: {problem.detail}",
        ) from None


def _names(raw, field: str) -> list[str]:
    """A short list of names (categories or merchants), tidied and without repeats."""
    raw = _default(raw, [])
    if not isinstance(raw, list) or len(raw) > MAX_CATEGORIES:
        raise _bad(f"{field} must be a list of at most {MAX_CATEGORIES} names.")
    names = []
    for item in raw:
        if not isinstance(item, str) or not item.strip() or len(item) > MAX_SERIES_KEY_LENGTH:
            raise _bad(f"{field} must contain names of up to {MAX_SERIES_KEY_LENGTH} characters.")
        tidy = " ".join(item.split())
        if tidy not in names:
            names.append(tidy)
    return names


def _whole_numbers(raw, field: str, low: int, high: int) -> list[int]:
    raw = _default(raw, [])
    if not isinstance(raw, list) or len(raw) > high - low + 1:
        raise _bad(f"{field} must be a list of whole numbers from {low} to {high}.")
    for item in raw:
        if isinstance(item, bool) or not isinstance(item, int) or not low <= item <= high:
            raise _bad(f"{field} must be a list of whole numbers from {low} to {high}.")
    return sorted(set(raw))


def validate_selection(raw) -> dict:
    """A click on a chart as a filter: what the clicked mark stands for.

    Used to filter the other panels ("filter the dashboard to Food") and to list the
    transactions behind a mark. Every key is optional and only the ones given are returned:
    categories, merchants and data sources by name (as a chart labels them), type, weekdays
    (0 = Monday), months of the year (1-12), and a date range.
    """
    raw = _default(raw, {})
    _only_keys(
        raw,
        ("categories", "type", "merchants", "data_sources", "weekdays", "months", "date"),
        "selection",
    )
    selection = {}
    if categories := _names(raw.get("categories"), "selection.categories"):
        selection["categories"] = categories
    if merchants := _names(raw.get("merchants"), "selection.merchants"):
        selection["merchants"] = merchants
    if data_sources := _names(raw.get("data_sources"), "selection.data_sources"):
        selection["data_sources"] = data_sources
    if raw.get("type") is not None:
        selection["type"] = _choice(raw["type"], TXN_TYPES, "selection.type")
    if weekdays := _whole_numbers(raw.get("weekdays"), "selection.weekdays", 0, 6):
        selection["weekdays"] = weekdays
    if months := _whole_numbers(raw.get("months"), "selection.months", 1, 12):
        selection["months"] = months
    if raw.get("date") is not None:
        span = raw["date"]
        _only_keys(span, ("from", "to"), "selection.date")
        start = _parse_date(span.get("from"), "selection.date.from")
        end = _parse_date(span.get("to"), "selection.date.to")
        if start > end:
            raise _bad("selection.date.from must not be after selection.date.to.")
        selection["date"] = {"from": start.isoformat(), "to": end.isoformat()}
    return selection


def catalogue() -> dict:
    """Everything the panel editor needs for its dropdowns, built from the same constants the
    validator uses, so the frontend never hard-codes a rule that could drift out of date."""
    return {
        "version": SPEC_VERSION,
        "dimensions": [
            {"id": name, "granularities": list(GRANULARITIES) if name == "date" else []}
            for name in DIMENSIONS
        ],
        "measures": [
            {"id": name, "aggs": list(allowed_aggs(name)), "default_agg": default_agg(name)}
            for name in MEASURES
        ],
        "charts": {
            chart: {"x": list(rules["x"]), "color": rules["color"]}
            for chart, rules in CHART_RULES.items()
        },
        "calcs": [
            {
                "id": kind,
                "needs_date": kind in TIME_CALCS,
                "additive_only": kind in ADDITIVE_CALCS,
                "never_negative": kind == "percent_of_total",
            }
            for kind in CALCS
        ],
        "kpi": {
            "compares": list(KPI_COMPARES),
            "directions": list(DIRECTIONS),
            "secondary": [
                {
                    "id": figure,
                    "needs_money_measure": figure != "count",
                    "needs_sum": figure == "share_of_income",
                }
                for figure in SECONDARY
            ],
            "money_measures": list(AMOUNT_MEASURES),
            "average_of": list(AVERAGE_OF_RANGE),
            "max_secondary": MAX_SECONDARY,
        },
        "format": {
            "numbers": list(NUMBER_FORMATS),
            "legends": list(LEGENDS),
            "charts": list(FORMAT_CHARTS),
            "legend_charts": list(LEGEND_CHARTS),
            "axis_charts": list(AXIS_CHARTS),
        },
        "rows_fields": list(CATEGORICAL),  # what a heatmap's rows can be
        "formula": {
            "charts": list(FORMULA_CHARTS),
            "agg": default_agg(FORMULA),  # the one aggregation a formula panel stores
            "forms": list(RESULT_FORMS),
            "max_length": FORMULA_MAX_LENGTH,
            **language(),  # the names, fields, functions and keywords the editor lists
        },
        "parameters": {
            "defaults": dict(PARAMETER_DEFAULTS),
            "measures": list(PARAMETER_MEASURES),
            "comparisons": list(PARAMETER_COMPARISONS),
            "top_n": list(LIMIT_RANGE),
            "bindings": dict(BINDINGS),
        },
        "change_vs": list(CHANGE_VS),
        "change_as": list(CHANGE_AS),
        "sorts": list(SORTS),
        "orientations": list(ORIENTATIONS),
        "txn_types": list(TXN_TYPES),
        "date_presets": list(DATE_PRESETS),
        "limits": {
            "limit": list(LIMIT_RANGE),
            "bins": list(BINS_RANGE),
            "categories": MAX_CATEGORIES,
            "data_sources": MAX_DATA_SOURCES,
            "merchant_contains": MAX_MERCHANT_LENGTH,
            "series_colors": MAX_SERIES_COLORS,
            "window": list(WINDOW_RANGE),
            "text": MAX_TEXT_LENGTH,
            "calendar_days": CALENDAR_MAX_DAYS,
        },
    }


# --- filters ------------------------------------------------------------------


def validate_date_filter(raw) -> dict:
    """{"preset": ...}, plus "from" / "to" for a custom range. "inherit" defers to the dashboard."""
    raw = _default(raw, {})
    _only_keys(raw, ("preset", "from", "to"), "filters.date")
    preset = _choice(_default(raw.get("preset"), "inherit"), ("inherit", *DATE_PRESETS), "preset")

    if preset != "custom":
        if raw.get("from") is not None or raw.get("to") is not None:
            raise _bad("from and to are only used with the custom preset.")
        return {"preset": preset}

    start = _parse_date(raw.get("from"), "filters.date.from")
    end = _parse_date(raw.get("to"), "filters.date.to")
    if start > end:
        raise _bad("filters.date.from must not be after filters.date.to.")
    return {"preset": "custom", "from": start.isoformat(), "to": end.isoformat()}


def _ids(raw, field: str, what: str, most: int) -> list[str]:
    """A list of ids with no duplicates, in the order given."""
    raw = _default(raw, [])
    if not isinstance(raw, list) or len(raw) > most:
        raise _bad(f"filters.{field} must be a list of at most {most} {what} ids.")
    clean = []
    for item in raw:
        try:
            clean.append(str(uuid.UUID(item)))
        except (ValueError, TypeError, AttributeError):
            raise _bad(f"filters.{field} must contain {what} ids.") from None
    return list(dict.fromkeys(clean))


def validate_filters(raw) -> dict:
    """The filters that decide which rows a panel sees. Used for panels and the dashboard bar."""
    raw = _default(raw, {})
    _only_keys(raw, ("date", "type", "categories", "data_sources", "merchant_contains"), "filters")

    txn_type = raw.get("type")
    if txn_type is not None:
        _choice(txn_type, TXN_TYPES, "filters.type")

    categories = _ids(raw.get("categories"), "categories", "category", MAX_CATEGORIES)
    data_sources = _ids(raw.get("data_sources"), "data_sources", "data source", MAX_DATA_SOURCES)

    text =_default(raw.get("merchant_contains"), "")
    if not isinstance(text, str) or len(text.strip()) > MAX_MERCHANT_LENGTH:
        raise _bad(
            f"filters.merchant_contains must be text of at most {MAX_MERCHANT_LENGTH} characters."
        )

    return {
        "date": validate_date_filter(raw.get("date")),
        "type": txn_type,
        "categories": categories,
        "data_sources": data_sources,
        "merchant_contains": text.strip(),
    }


# --- series colours -----------------------------------------------------------


def validate_series_colors(raw) -> dict:
    """The user's colour overrides: {series value: "#RRGGBB"}.

    The key is the raw value of the thing being coloured (a category name, "credit", a month),
    or "_" for a chart with a single series. Colours are stored upper case. The keys are only
    ever looked up by the frontend, never used as a field name or query, but they are bounded
    so a panel config can't grow without limit.
    """
    raw = _default(raw, {})
    if not isinstance(raw, dict):
        raise _bad("series_colors must be an object.")
    if len(raw) > MAX_SERIES_COLORS:
        raise _bad(f"series_colors can have at most {MAX_SERIES_COLORS} entries.")
    clean = {}
    for key, color in raw.items():
        if not isinstance(key, str) or not 0 < len(key) <= MAX_SERIES_KEY_LENGTH:
            raise _bad(f"series_colors keys must be 1 to {MAX_SERIES_KEY_LENGTH} characters.")
        if not isinstance(color, str) or not is_hex_color(color.upper()):
            raise _bad("series_colors values must be colours like #2A78D6.")
        clean[key] = color.upper()
    return clean


# --- the whole spec -----------------------------------------------------------


# --- versions -----------------------------------------------------------------


def _v1_to_v2(raw: dict) -> dict:
    """Version 2 only added the optional `calc`, so a version 1 spec is already valid."""
    return {**raw, "v": 2}


def _v2_to_v3(raw: dict) -> dict:
    """Version 3 replaced the KPI's `compare: true` with `kpi: {compare: "previous"}`."""
    if "kpi" in raw:
        raise _bad("Unknown keys in spec: kpi.")  # a version 2 spec never had it
    raw = dict(raw)
    compare = raw.pop("compare", None)
    if compare is not None and not isinstance(compare, bool):
        raise _bad("compare must be true or false.")
    if compare:
        if raw.get("chart") != "kpi":
            raise _bad("Only a KPI can compare with the previous period.")
        raw["kpi"] = {"compare": "previous"}
    raw["v"] = 3
    return raw


def _v3_to_v4(raw: dict) -> dict:
    """Version 4 only added the optional `format` and the `text` chart."""
    return {**raw, "v": 4}


def _v4_to_v5(raw: dict) -> dict:
    """Version 5 only added the calendar and heatmap charts, and their `rows` field."""
    return {**raw, "v": 5}


def _v5_to_v6(raw: dict) -> dict:
    """Version 6 only added the optional `bind` (fields that follow dashboard parameters)."""
    return {**raw, "v": 6}


def _v6_to_v7(raw: dict) -> dict:
    """Version 7 only added the optional calculated field (a `formula` inside `y`)."""
    return {**raw, "v": 7}


def _v7_to_v8(raw: dict) -> dict:
    """Version 8 only widened the formula language, so a version 7 spec is already valid."""
    return {**raw, "v": 8}


def _v8_to_v9(raw: dict) -> dict:
    """Version 9 added data sources. Filters default to every source, so nothing else changes."""
    return {**raw, "v": 9}


# version -> the function that turns a spec of that version into the next one
UPGRADES = {
    1: _v1_to_v2,
    2: _v2_to_v3,
    3: _v3_to_v4,
    4: _v4_to_v5,
    5: _v5_to_v6,
    6: _v6_to_v7,
    7: _v7_to_v8,
    8: _v8_to_v9,
}


def upgrade(raw) -> dict:
    """Bring a spec of any supported version to SPEC_VERSION, one version at a time.

    A spec without "v" is taken to be current. Raises SpecError for an unknown version.
    """
    if not isinstance(raw, dict):
        raise _bad("The spec must be an object.")
    version = _default(raw.get("v"), SPEC_VERSION)
    if (
        isinstance(version, bool)
        or not isinstance(version, int)
        or not 1 <= version <= SPEC_VERSION
    ):
        raise SpecError("unsupported_version", f"Spec version {version!r} is not supported.")
    while version < SPEC_VERSION:
        raw = UPGRADES[version](raw)
        version += 1
    return raw


def validate_spec(raw: dict) -> dict:
    """Validate a whole panel config. Idempotent: validating a clean spec returns it unchanged."""
    raw = upgrade(raw)
    if raw.get("chart") == "text":
        return validate_text(raw)
    _only_keys(raw, SPEC_KEYS, "spec")

    spec = validate_encoding(raw)
    calc = validate_calc(raw.get("calc"), spec)
    if calc:
        spec["calc"] = calc
    kpi = validate_kpi(raw.get("kpi"), spec)
    if kpi:
        spec["kpi"] = kpi
    formatting = validate_format(raw.get("format"), spec)
    if formatting:
        spec["format"] = formatting
    bind = validate_bind(raw.get("bind"), spec)
    if bind:
        spec["bind"] = bind
    spec["v"] = SPEC_VERSION
    spec["filters"] = validate_filters(raw.get("filters"))
    spec["stacked"] = _bool(raw.get("stacked"), "stacked")
    spec["orientation"] = _choice(
        _default(raw.get("orientation"), "vertical"), ORIENTATIONS, "orientation"
    )
    spec["series_colors"] = validate_series_colors(raw.get("series_colors"))
    return spec


# --- periods ------------------------------------------------------------------


def _preset_range(date_filter: dict, today: date) -> tuple[date, date]:
    preset = date_filter["preset"]
    month_start = today.replace(day=1)

    if preset == "this_month":
        return month_start, today
    if preset == "last_month":
        end = month_start - timedelta(days=1)
        return end.replace(day=1), end
    if preset == "last_3_months":  # this month and the two before it
        return add_months(month_start, -2), today
    if preset == "last_12_months":  # this month and the eleven before it
        return add_months(month_start, -11), today
    if preset == "this_year":
        return today.replace(month=1, day=1), today
    if preset == "all":  # the services layer trims the start to the user's first transaction
        return MIN_DATE, today
    if preset == "custom":
        return date.fromisoformat(date_filter["from"]), date.fromisoformat(date_filter["to"])
    raise ValueError(f"Unknown date preset: {preset!r}")


def resolve_period(panel_date: dict, dashboard_date: dict, today: date) -> tuple[date, date]:
    """The (start, end) a panel shows. Both arguments are validated `filters["date"]` dicts.

    A panel's own preset wins; "inherit" falls back to the dashboard's, and if that also
    inherits, to DEFAULT_PRESET. `today` is passed in so tests don't depend on the clock.
    """
    chosen = panel_date
    if chosen["preset"] == "inherit":
        chosen = dashboard_date
    if chosen["preset"] == "inherit":
        chosen = {"preset": DEFAULT_PRESET}
    return _preset_range(chosen, today)

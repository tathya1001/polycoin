"""Validation for panel specs: the only door between JSON from the browser and the engine.

`validate_spec` whitelists every key and value, fills in defaults, and returns the clean
shape the engine reads. Saved panel configs go through it on the way in AND on the way out,
so a config written by an older version can never reach the engine unchecked.
"""

import uuid
from datetime import date, timedelta

from .engine import DIMENSIONS, GRANULARITIES, MEASURES, add_months

SPEC_VERSION = 1

CATEGORICAL = tuple(dimension for dimension in DIMENSIONS if dimension != "date")
CHARTS = ("kpi", "bar", "line", "area", "pie", "donut", "histogram")
SORTS = ("measure_desc", "label")
ORIENTATIONS = ("vertical", "horizontal")
TXN_TYPES = ("credit", "debit")
SPEC_KEYS = (
    "v", "chart", "x", "y", "color", "sort", "limit", "bins", "compare",
    "stacked", "orientation", "filters",
)  # fmt: skip

DATE_PRESETS = (
    "this_month", "last_month", "last_3_months", "last_12_months", "this_year", "all", "custom",
)  # fmt: skip
DEFAULT_PRESET = "last_3_months"  # used when neither the panel nor the dashboard picks one
MIN_DATE = date(2000, 1, 1)
MAX_DATE = date(2100, 12, 31)
MAX_CATEGORIES = 20
MAX_MERCHANT_LENGTH = 60

# Which fields each chart may use for x, and whether it may split into a colour series.
# Served to the frontend later so the editor can grey out invalid combinations.
CHART_RULES = {
    "kpi": {"x": (), "color": False},
    "bar": {"x": ("date", *CATEGORICAL), "color": True},
    "line": {"x": ("date",), "color": True},
    "area": {"x": ("date",), "color": True},
    "pie": {"x": CATEGORICAL, "color": False},
    "donut": {"x": CATEGORICAL, "color": False},
    "histogram": {"x": (), "color": False},
}


class SpecError(Exception):
    """A rejected panel spec. Same {code, detail} idea as AIError and ImportProblem."""

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
    return ("sum", "avg", "min", "max", "median")


def default_agg(measure: str) -> str:
    return allowed_aggs(measure)[0]


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
    _only_keys(y_raw, ("measure", "agg"), "y")
    measure = _choice(y_raw.get("measure"), MEASURES, "y.measure")
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
    spec["limit"] = _int_in_range(raw.get("limit"), 1, 50, "limit", 10)
    spec["bins"] = _int_in_range(raw.get("bins"), 5, 50, "bins", 20)
    compare = _bool(raw.get("compare"), "compare")
    if compare and chart != "kpi":
        raise _bad("Only a KPI can compare with the previous period.")
    spec["compare"] = compare
    return spec


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


def validate_filters(raw) -> dict:
    """The filters that decide which rows a panel sees. Used for panels and the dashboard bar."""
    raw = _default(raw, {})
    _only_keys(raw, ("date", "type", "categories", "merchant_contains"), "filters")

    txn_type = raw.get("type")
    if txn_type is not None:
        _choice(txn_type, TXN_TYPES, "filters.type")

    categories = _default(raw.get("categories"), [])
    if not isinstance(categories, list) or len(categories) > MAX_CATEGORIES:
        raise _bad(f"filters.categories must be a list of at most {MAX_CATEGORIES} category ids.")
    clean_ids = []
    for item in categories:
        try:
            clean_ids.append(str(uuid.UUID(item)))
        except (ValueError, TypeError, AttributeError):
            raise _bad("filters.categories must contain category ids.") from None

    text = _default(raw.get("merchant_contains"), "")
    if not isinstance(text, str) or len(text.strip()) > MAX_MERCHANT_LENGTH:
        raise _bad(
            f"filters.merchant_contains must be text of at most {MAX_MERCHANT_LENGTH} characters."
        )

    return {
        "date": validate_date_filter(raw.get("date")),
        "type": txn_type,
        "categories": list(dict.fromkeys(clean_ids)),  # no duplicates, order kept
        "merchant_contains": text.strip(),
    }


# --- the whole spec -----------------------------------------------------------


def validate_spec(raw: dict) -> dict:
    """Validate a whole panel config. Idempotent: validating a clean spec returns it unchanged."""
    if not isinstance(raw, dict):
        raise _bad("The spec must be an object.")
    _only_keys(raw, SPEC_KEYS, "spec")

    version = _default(raw.get("v"), SPEC_VERSION)
    if isinstance(version, bool) or version != SPEC_VERSION:
        raise SpecError("unsupported_version", f"Spec version {version!r} is not supported.")

    spec = validate_encoding(raw)
    spec["v"] = SPEC_VERSION
    spec["filters"] = validate_filters(raw.get("filters"))
    spec["stacked"] = _bool(raw.get("stacked"), "stacked")
    spec["orientation"] = _choice(
        _default(raw.get("orientation"), "vertical"), ORIENTATIONS, "orientation"
    )
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

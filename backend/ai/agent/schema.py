"""What the model returns for one panel request: a flat, typed intent, never a panel spec.

Every choice is an enum built from the constants that insights/spec.py validates against, so
the two cannot drift apart. `ollama_schema()` is sent to Ollama as the `format` of the chat
request; constrained decoding then makes the model emit valid JSON with only these keys and
values. The reply still comes back through the user's browser, so `parse_intent` treats it as
untrusted and checks it again here.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from insights.engine import DIMENSIONS, GRANULARITIES, MEASURES
from insights.spec import (
    AVERAGE_OF_RANGE,
    CALCS,
    CATEGORICAL,
    CHANGE_AS,
    CHANGE_VS,
    CHARTS,
    DATE_PRESETS,
    DIRECTIONS,
    KPI_COMPARES,
    LIMIT_RANGE,
    MAX_CATEGORIES,
    MAX_DATA_SOURCES,
    MAX_MERCHANT_LENGTH,
    SORTS,
    TXN_TYPES,
    WINDOW_RANGE,
    allowed_aggs,
)

from ..rag.answer import flatten
from .errors import AgentError

# A text panel holds no data, so the builder never makes one.
AGENT_CHARTS = tuple(chart for chart in CHARTS if chart != "text")
# Every aggregation some measure allows, in the validator's order.
AGENT_AGGS = tuple(dict.fromkeys(agg for measure in MEASURES for agg in allowed_aggs(measure)))
KINDS = ("panel", "not_a_panel")

MAX_TITLE_LENGTH = 80
MAX_REASON_LENGTH = 200
MAX_CATEGORY_NAME_LENGTH = 50  # the Category.name column
MAX_REPLY_CHARS = 4000  # a full intent is about 600 characters
MAX_ERRORS = 5  # problems listed in one error detail
DATE_PATTERN = r"^\d{4}-\d{2}-\d{2}$"


class PanelIntent(BaseModel):
    """One panel request, as the model understood it. Unset means "use the default"."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    kind: Literal[KINDS]
    reason: str | None = Field(default=None, max_length=MAX_REASON_LENGTH)  # for not_a_panel
    title: str | None = Field(default=None, max_length=MAX_TITLE_LENGTH)

    chart: Literal[AGENT_CHARTS] | None = None
    measure: Literal[MEASURES] | None = None
    agg: Literal[AGENT_AGGS] | None = None
    x: Literal[DIMENSIONS] | None = None
    granularity: Literal[GRANULARITIES] | None = None
    color: Literal[CATEGORICAL] | None = None
    rows: Literal[CATEGORICAL] | None = None  # a heatmap's second field

    period: Literal[DATE_PRESETS] | None = None  # unset: the dashboard's period
    date_from: str | None = Field(default=None, pattern=DATE_PATTERN)  # only for "custom"
    date_to: str | None = Field(default=None, pattern=DATE_PATTERN)
    categories: list[str] = Field(default_factory=list, max_length=MAX_CATEGORIES)  # names
    data_sources: list[str] = Field(default_factory=list, max_length=MAX_DATA_SOURCES)  # names
    merchant: str | None = Field(default=None, max_length=MAX_MERCHANT_LENGTH)  # user's words
    txn_type: Literal[TXN_TYPES] | None = None

    limit: int | None = Field(default=None, ge=LIMIT_RANGE[0], le=LIMIT_RANGE[1])
    sort: Literal[SORTS] | None = None

    compare: Literal[KPI_COMPARES] | None = None
    direction: Literal[DIRECTIONS] | None = None
    average_of: int | None = Field(default=None, ge=AVERAGE_OF_RANGE[0], le=AVERAGE_OF_RANGE[1])

    calc: Literal[CALCS] | None = None
    window: int | None = Field(default=None, ge=WINDOW_RANGE[0], le=WINDOW_RANGE[1])
    change_vs: Literal[CHANGE_VS] | None = None
    change_as: Literal[CHANGE_AS] | None = None

    @field_validator("reason", "title", "merchant")
    @classmethod
    def _one_safe_line(cls, value: str | None) -> str | None:
        """Shown to the user and maybe sent back to the model: one line, no tags, None if empty."""
        if value is None:
            return None
        return flatten(value) or None

    @field_validator("data_sources", mode="before")
    @classmethod
    def _null_is_none_named(cls, value):
        return [] if value is None else value

    @field_validator("categories", "data_sources")
    @classmethod
    def _names(cls, names: list[str]) -> list[str]:
        clean = []
        for name in names:
            name = flatten(name)
            if len(name) > MAX_CATEGORY_NAME_LENGTH:
                raise ValueError(f"each name must be at most {MAX_CATEGORY_NAME_LENGTH} characters")
            if name:
                clean.append(name)
        return list(dict.fromkeys(clean))  # no duplicates, order kept


def _strip_metadata(node):
    """Drop the "title", "default" and "description" annotations Pydantic adds: constrained
    decoding ignores them, and they only make the request bigger. Keys inside "properties" are
    field names (one of them is "title"), so those are kept."""
    if isinstance(node, list):
        return [_strip_metadata(item) for item in node]
    if not isinstance(node, dict):
        return node
    clean = {}
    for key, value in node.items():
        if key == "properties":
            clean[key] = {name: _strip_metadata(field) for name, field in value.items()}
        elif key not in ("title", "default", "description"):
            clean[key] = _strip_metadata(value)
    return clean


def ollama_schema() -> dict:
    """The JSON schema for Ollama's `format`. Every key is required, so the model always writes
    the full intent in the same order and says "null" for what it leaves unset."""
    schema = _strip_metadata(PanelIntent.model_json_schema())
    schema["required"] = list(schema["properties"])
    return schema


def _safe_problems(problem: ValidationError) -> str:
    """One short line per bad field. Never the input: the reply is model output relayed by the
    browser, so it may hold anything, and the detail is logged and sent back to the model. An
    unknown key is the model's own text, so it is not named either."""
    lines = {}
    for error in problem.errors(include_url=False, include_input=False, include_context=False):
        field = error["loc"][0] if error["loc"] else None
        if field not in PanelIntent.model_fields:
            field = "reply"
        message = "unknown key" if error["type"] == "extra_forbidden" else error["msg"]
        lines.setdefault(field, f"{field}: {message}")
    return "; ".join(list(lines.values())[:MAX_ERRORS])


def parse_intent(reply: str) -> PanelIntent:
    """Parse the model's raw reply. Raises AgentError("bad_reply", safe detail)."""
    if not isinstance(reply, str) or len(reply) > MAX_REPLY_CHARS:
        raise AgentError(
            "bad_reply", f"The reply must be text of at most {MAX_REPLY_CHARS} characters."
        )
    try:
        return PanelIntent.model_validate_json(reply)
    except ValidationError as problem:
        raise AgentError("bad_reply", _safe_problems(problem)) from None

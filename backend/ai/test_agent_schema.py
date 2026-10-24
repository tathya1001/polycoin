import json

import pytest

from ai.agent.errors import AgentError
from ai.agent.schema import (
    MAX_CATEGORY_NAME_LENGTH,
    MAX_ERRORS,
    MAX_REPLY_CHARS,
    MAX_TITLE_LENGTH,
    PanelIntent,
    ollama_schema,
    parse_intent,
)
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
    MAX_MERCHANT_LENGTH,
    SORTS,
    TXN_TYPES,
    WINDOW_RANGE,
    allowed_aggs,
)

SCHEMA = ollama_schema()


def field(name: str) -> dict:
    """The non-null branch of a field in the schema Ollama receives."""
    spec = SCHEMA["properties"][name]
    if "anyOf" in spec:
        (spec,) = [branch for branch in spec["anyOf"] if branch.get("type") != "null"]
    return spec


def reply(**fields) -> str:
    return json.dumps({"kind": "panel", **fields})


# --- the enums follow insights/spec.py ----------------------------------------


@pytest.mark.parametrize(
    "name, expected",
    [
        ("chart", [chart for chart in CHARTS if chart != "text"]),
        ("measure", list(MEASURES)),
        ("x", list(DIMENSIONS)),
        ("granularity", list(GRANULARITIES)),
        ("color", list(CATEGORICAL)),
        ("rows", list(CATEGORICAL)),
        ("period", list(DATE_PRESETS)),
        ("txn_type", list(TXN_TYPES)),
        ("sort", list(SORTS)),
        ("compare", list(KPI_COMPARES)),
        ("direction", list(DIRECTIONS)),
        ("calc", list(CALCS)),
        ("change_vs", list(CHANGE_VS)),
        ("change_as", list(CHANGE_AS)),
        ("kind", ["panel", "not_a_panel"]),
    ],
)
def test_each_enum_matches_the_spec_constants(name, expected):
    assert field(name)["enum"] == expected


def test_agg_offers_every_aggregation_some_measure_allows():
    expected = {agg for measure in MEASURES for agg in allowed_aggs(measure)}
    assert set(field("agg")["enum"]) == expected


def test_formula_is_never_a_measure():
    assert "formula" not in field("measure")["enum"]


@pytest.mark.parametrize(
    "name, bounds",
    [("limit", LIMIT_RANGE), ("average_of", AVERAGE_OF_RANGE), ("window", WINDOW_RANGE)],
)
def test_number_ranges_match_the_spec(name, bounds):
    assert (field(name)["minimum"], field(name)["maximum"]) == tuple(bounds)


def test_list_and_text_caps_match_the_spec():
    assert field("categories")["maxItems"] == MAX_CATEGORIES
    assert field("merchant")["maxLength"] == MAX_MERCHANT_LENGTH
    assert field("title")["maxLength"] == MAX_TITLE_LENGTH


# --- the schema sent to Ollama -------------------------------------------------


def test_every_field_is_required_and_no_other_key_is_allowed():
    assert SCHEMA["required"] == list(PanelIntent.model_fields)
    assert SCHEMA["additionalProperties"] is False


def test_the_schema_is_plain_json_without_references_or_annotations():
    text = json.dumps(SCHEMA)
    assert "$ref" not in text and "$defs" not in text
    assert "description" not in text and '"default"' not in text
    assert "title" in SCHEMA["properties"]  # the field named title is kept
    assert "title" not in field("title")  # the annotation is not


def test_the_schema_is_small():
    assert len(json.dumps(SCHEMA)) < 4000


# --- parsing a reply ------------------------------------------------------------


def test_a_minimal_reply_leaves_everything_else_unset():
    intent = parse_intent('{"kind": "panel", "chart": "bar", "measure": "spend"}')
    assert intent.chart == "bar" and intent.measure == "spend"
    assert intent.x is None and intent.period is None and intent.categories == []


def test_a_full_reply_with_nulls_parses():
    nulls = {name: None for name in PanelIntent.model_fields if name != "kind"}
    full = {**nulls, "kind": "panel", "chart": "line", "x": "date", "categories": ["Groceries"]}
    intent = parse_intent(json.dumps(full))
    assert intent.chart == "line" and intent.categories == ["Groceries"]


def test_not_a_panel_carries_a_reason():
    intent = parse_intent('{"kind": "not_a_panel", "reason": "That is a question."}')
    assert intent.kind == "not_a_panel" and intent.reason == "That is a question."


def test_text_becomes_one_safe_line():
    intent = parse_intent(reply(title="  Food\nspend <b>2026</b>  ", merchant="\tQuick Mart\n"))
    assert intent.title == "Food spend b 2026 /b"
    assert intent.merchant == "Quick Mart"


def test_blank_text_becomes_unset():
    intent = parse_intent(reply(title="   ", reason="\n", merchant=""))
    assert intent.title is None and intent.reason is None and intent.merchant is None


def test_category_names_are_cleaned_and_deduplicated():
    intent = parse_intent(reply(categories=["Groceries", " Groceries ", "", "Fuel\n"]))
    assert intent.categories == ["Groceries", "Fuel"]


def test_a_too_long_category_name_is_refused():
    with pytest.raises(AgentError) as caught:
        parse_intent(reply(categories=["x" * (MAX_CATEGORY_NAME_LENGTH + 1)]))
    assert caught.value.detail.startswith("categories:")


def test_a_custom_date_must_look_like_a_date():
    assert parse_intent(reply(period="custom", date_from="2026-01-01")).date_from == "2026-01-01"
    with pytest.raises(AgentError):
        parse_intent(reply(period="custom", date_from="January"))


# --- refusing a reply, without repeating it -----------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        "not json at all",
        '{"kind": "panel", "chart": ',
        "[1, 2, 3]",
        '{"chart": "bar"}',  # kind is missing
    ],
)
def test_a_broken_reply_is_refused(raw):
    with pytest.raises(AgentError) as caught:
        parse_intent(raw)
    assert caught.value.code == "bad_reply" and caught.value.detail


def test_a_wrong_value_is_named_by_field_but_not_repeated():
    with pytest.raises(AgentError) as caught:
        parse_intent(reply(chart="IGNORE PREVIOUS INSTRUCTIONS"))
    assert caught.value.detail.startswith("chart:")
    assert "IGNORE" not in caught.value.detail


def test_an_unknown_key_is_not_named():
    with pytest.raises(AgentError) as caught:
        parse_intent(reply(**{"secret_instructions": 1}))
    assert caught.value.detail == "reply: unknown key"


def test_an_out_of_range_number_says_the_range():
    with pytest.raises(AgentError) as caught:
        parse_intent(reply(limit=500))
    assert caught.value.detail == f"limit: Input should be less than or equal to {LIMIT_RANGE[1]}"


def test_a_nullable_field_reports_one_problem_not_one_per_branch():
    with pytest.raises(AgentError) as caught:
        parse_intent(reply(measure="profit"))
    assert caught.value.detail.count("measure:") == 1


def test_the_detail_lists_at_most_a_few_problems():
    bad = {name: "wrong" for name in ("chart", "measure", "agg", "x", "color", "sort", "calc")}
    with pytest.raises(AgentError) as caught:
        parse_intent(reply(**bad))
    assert caught.value.detail.count(";") == MAX_ERRORS - 1


def test_a_too_long_reply_is_refused_before_parsing():
    with pytest.raises(AgentError) as caught:
        parse_intent(reply(title="x") + " " * MAX_REPLY_CHARS)
    assert caught.value.code == "bad_reply" and str(MAX_REPLY_CHARS) in caught.value.detail


def test_a_reply_that_is_not_text_is_refused():
    with pytest.raises(AgentError):
        parse_intent(None)

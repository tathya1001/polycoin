"""Formatting options and text panels (spec version 4)."""

import pytest

from insights import services
from insights.spec import (
    MAX_TEXT_LENGTH,
    SPEC_VERSION,
    SpecError,
    catalogue,
    upgrade,
    validate_spec,
)
from transactions.tests import make_user

BAR = {"chart": "bar", "x": {"field": "category"}, "y": {"measure": "spend"}}
DEFAULT_FORMAT = {
    "labels": False,
    "number": "auto",
    "legend": "auto",
    "axis": {"min": None, "max": None},
}


def formatted(chart=None, **fmt):
    return validate_spec({**(chart or BAR), "format": fmt})


# --- format ----------------------------------------------------------------------------


def test_a_chart_without_format_gets_the_defaults_that_change_nothing():
    for chart in (
        BAR,
        {
            "chart": "line",
            "x": {"field": "date", "granularity": "month"},
            "y": {"measure": "spend"},
        },
        {"chart": "pie", "x": {"field": "category"}, "y": {"measure": "spend"}},
        {"chart": "histogram", "y": {"measure": "spend"}},
    ):
        assert validate_spec(chart)["format"] == DEFAULT_FORMAT


def test_format_options_are_kept_and_round_trip():
    spec = formatted(
        labels=True, number="compact", legend="bottom", axis={"min": 0, "max": 50000.5}
    )
    assert spec["format"] == {
        "labels": True,
        "number": "compact",
        "legend": "bottom",
        "axis": {"min": 0, "max": 50000.5},
    }
    assert validate_spec(spec) == spec


def test_old_specs_gain_the_defaults_when_read():
    for version in range(1, SPEC_VERSION):
        assert validate_spec({**BAR, "v": version})["format"] == DEFAULT_FORMAT


@pytest.mark.parametrize(
    "fmt",
    [
        {"labels": "yes"},
        {"number": "percent"},
        {"legend": "left"},
        {"axis": {"min": "0"}},
        {"axis": {"min": True}},
        {"axis": {"min": float("nan")}},
        {"axis": {"max": 1e13}},
        {"axis": {"min": 10, "max": 10}},
        {"axis": {"min": 20, "max": 10}},
        {"axis": {"low": 1}},
        {"axis": [0, 1]},
        {"sparkles": True},
    ],
)
def test_impossible_formats_are_refused(fmt):
    with pytest.raises(SpecError):
        formatted(**fmt)


def test_a_bound_may_be_given_alone():
    assert formatted(axis={"min": 0})["format"]["axis"] == {"min": 0, "max": None}
    assert formatted(axis={"max": 100})["format"]["axis"] == {"min": None, "max": 100}


def test_a_chart_only_takes_the_options_it_has():
    pie = {"chart": "pie", "x": {"field": "category"}, "y": {"measure": "spend"}}
    histogram = {"chart": "histogram", "y": {"measure": "spend"}}
    assert formatted(pie, labels=True, legend="right")["format"]["legend"] == "right"
    with pytest.raises(SpecError):
        formatted(pie, axis={"min": 0})  # no value axis
    with pytest.raises(SpecError):
        formatted(histogram, legend="top")  # no legend
    assert formatted(histogram, labels=True)["format"]["labels"] is True
    kpi = {"chart": "kpi", "y": {"measure": "spend"}}
    with pytest.raises(SpecError):
        validate_spec({**kpi, "format": {}})
    assert "format" not in validate_spec(kpi)


def test_the_catalogue_lists_the_formatting_rules():
    rules = catalogue()["format"]
    assert rules["numbers"] == ["auto", "full", "compact"]
    assert "pie" in rules["legend_charts"] and "pie" not in rules["axis_charts"]
    assert catalogue()["limits"]["text"] == MAX_TEXT_LENGTH


# --- text panels -----------------------------------------------------------------------


def test_a_text_panel_is_just_its_words():
    spec = validate_spec({"chart": "text", "text": "## Budget\nKeep **food** under ₹10,000."})
    assert spec == {
        "v": SPEC_VERSION,
        "chart": "text",
        "text": "## Budget\nKeep **food** under ₹10,000.",
    }
    assert validate_spec(spec) == spec


def test_text_defaults_to_empty_and_normalises_line_endings():
    assert validate_spec({"chart": "text"})["text"] == ""
    assert validate_spec({"chart": "text", "text": "a\r\nb"})["text"] == "a\nb"


@pytest.mark.parametrize(
    "raw",
    [
        {"chart": "text", "text": 5},
        {"chart": "text", "text": "x" * (MAX_TEXT_LENGTH + 1)},
        {"chart": "text", "text": "ok", "y": {"measure": "spend"}},
        {"chart": "text", "text": "ok", "filters": {}},
        {"chart": "text", "text": "ok", "format": {}},
        {"chart": "bar", "x": {"field": "category"}, "y": {"measure": "spend"}, "text": "no"},
    ],
)
def test_text_panels_take_nothing_but_text(raw):
    with pytest.raises(SpecError):
        validate_spec(raw)


def test_text_of_exactly_the_limit_is_fine():
    assert (
        len(validate_spec({"chart": "text", "text": "x" * MAX_TEXT_LENGTH})["text"])
        == MAX_TEXT_LENGTH
    )


def test_markup_in_a_text_panel_is_stored_as_the_words_it_is():
    hostile = "<script>alert(1)</script> [x](javascript:alert(1)) ![i](http://evil.example/p.png)"
    assert (
        validate_spec({"chart": "text", "text": hostile})["text"] == hostile
    )  # shown as text only


@pytest.mark.django_db
def test_a_text_panel_runs_no_query():
    assert upgrade({"chart": "text", "v": 1})["v"] == SPEC_VERSION
    alice = make_user("alice@example.com")
    result = services.run_queries(
        alice, {}, [{"key": "note", "spec": {"chart": "text", "text": "hi"}}]
    )
    assert result == {"note": {"columns": [], "rows": [], "meta": {"chart": "text"}}}

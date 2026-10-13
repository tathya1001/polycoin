import uuid
from datetime import date

import pytest

from insights.spec import (
    DEFAULT_PRESET,
    MAX_CATEGORIES,
    MAX_DATE,
    MIN_DATE,
    SpecError,
    resolve_period,
    validate_date_filter,
    validate_encoding,
    validate_filters,
    validate_spec,
)

TODAY = date(2026, 10, 11)
INHERIT = {"preset": "inherit"}


def rejected(call, *args, code="invalid_spec"):
    with pytest.raises(SpecError) as caught:
        call(*args)
    assert caught.value.code == code


# --- validate_encoding --------------------------------------------------------


def enc(**override):
    base = {"chart": "bar", "x": {"field": "category"}, "y": {"measure": "spend", "agg": "sum"}}
    base.update(override)
    return base


def test_a_valid_bar_gets_its_defaults_filled_in():
    assert validate_encoding(enc()) == {
        "chart": "bar",
        "x": {"field": "category"},
        "y": {"measure": "spend", "agg": "sum"},
        "sort": "measure_desc",
        "limit": 10,
        "bins": 20,
        "compare": False,
    }


def test_the_aggregation_defaults_depend_on_the_measure():
    assert validate_encoding(enc(y={"measure": "spend"}))["y"]["agg"] == "sum"
    assert validate_encoding(enc(y={"measure": "balance"}))["y"]["agg"] == "last"
    assert validate_encoding(enc(y={"measure": "count"}))["y"]["agg"] == "sum"


def test_null_means_not_set():
    spec = validate_encoding(
        enc(y={"measure": "spend", "agg": None}, sort=None, limit=None, bins=None, compare=None)
    )
    assert spec["y"]["agg"] == "sum"
    defaults = (spec["sort"], spec["limit"], spec["bins"], spec["compare"])
    assert defaults == ("measure_desc", 10, 20, False)


@pytest.mark.parametrize(
    "y",
    [
        {"measure": "balance", "agg": "sum"},  # a balance is a snapshot
        {"measure": "spend", "agg": "last"},
        {"measure": "count", "agg": "avg"},
        {"measure": "profit", "agg": "sum"},
        {"measure": "spend", "agg": "total"},
        {"measure": "spend", "agg": "sum", "extra": 1},
        None,
        "spend",
    ],
)
def test_bad_y_is_rejected(y):
    rejected(validate_encoding, enc(y=y))


def test_a_time_axis_needs_a_granularity_and_nothing_else_may_have_one():
    ok = validate_encoding(enc(chart="line", x={"field": "date", "granularity": "month"}))
    assert ok["x"] == {"field": "date", "granularity": "month"}
    rejected(validate_encoding, enc(chart="line", x={"field": "date"}))
    rejected(validate_encoding, enc(chart="line", x={"field": "date", "granularity": "fortnight"}))
    rejected(validate_encoding, enc(x={"field": "category", "granularity": "month"}))


def test_chart_types_restrict_the_x_field():
    rejected(validate_encoding, enc(chart="line", x={"field": "category"}))  # a line needs time
    rejected(validate_encoding, enc(chart="pie", x={"field": "date", "granularity": "month"}))
    rejected(validate_encoding, enc(x={"field": "balance"}))
    rejected(validate_encoding, enc(x=None))
    rejected(validate_encoding, {"y": {"measure": "spend"}})  # no chart at all
    rejected(validate_encoding, enc(chart="radar"))
    rejected(validate_encoding, None)


def test_a_kpi_has_no_x_axis():
    assert "x" not in validate_encoding({"chart": "kpi", "y": {"measure": "net"}})
    with_x = {"chart": "kpi", "x": {"field": "category"}, "y": {"measure": "net"}}
    rejected(validate_encoding, with_x)


def test_pie_rules():
    rejected(validate_encoding, enc(chart="pie", color={"field": "txn_type"}))
    rejected(validate_encoding, enc(chart="pie", y={"measure": "net", "agg": "sum"}))
    validate_encoding(enc(chart="donut", y={"measure": "income", "agg": "sum"}))


def test_colour_rules():
    assert validate_encoding(enc(color={"field": "txn_type"}))["color"] == {"field": "txn_type"}
    rejected(validate_encoding, enc(color={"field": "category"}))  # same as x
    rejected(validate_encoding, enc(color={"field": "date"}))
    kpi_with_colour = {"chart": "kpi", "y": {"measure": "net"}, "color": {"field": "category"}}
    rejected(validate_encoding, kpi_with_colour)


def test_histogram_ignores_the_aggregation_and_rejects_count():
    spec = validate_encoding({"chart": "histogram", "y": {"measure": "spend", "agg": "avg"}})
    assert spec["y"] == {"measure": "spend", "agg": "sum"}
    rejected(validate_encoding, {"chart": "histogram", "y": {"measure": "count"}})


@pytest.mark.parametrize(
    "name, bad",
    [
        ("limit", 0),
        ("limit", 51),
        ("limit", True),
        ("limit", "10"),
        ("bins", 4),
        ("bins", 51),
        ("bins", 2.5),
    ],
)
def test_limit_and_bins_are_bounded_whole_numbers(name, bad):
    rejected(validate_encoding, enc(**{name: bad}))


def test_compare_is_a_boolean_and_only_for_kpis():
    kpi = {"chart": "kpi", "y": {"measure": "spend"}, "compare": True}
    assert validate_encoding(kpi)["compare"] is True
    rejected(validate_encoding, enc(compare=True))
    rejected(validate_encoding, {"chart": "kpi", "y": {"measure": "spend"}, "compare": "yes"})


# --- validate_date_filter -----------------------------------------------------


def test_the_date_filter_defaults_to_inherit():
    assert validate_date_filter(None) == INHERIT
    assert validate_date_filter({}) == INHERIT


def test_a_named_preset_is_accepted():
    assert validate_date_filter({"preset": "last_12_months"}) == {"preset": "last_12_months"}


def test_a_custom_range_is_normalised():
    result = validate_date_filter({"preset": "custom", "from": "2026-01-01", "to": "2026-03-31"})
    assert result == {"preset": "custom", "from": "2026-01-01", "to": "2026-03-31"}


@pytest.mark.parametrize(
    "raw",
    [
        {"preset": "last_decade"},
        {"preset": "custom"},  # no dates
        {"preset": "custom", "from": "2026-01-01"},
        {"preset": "custom", "from": "2026-03-31", "to": "2026-01-01"},  # backwards
        {"preset": "custom", "from": "2026-1-5", "to": "2026-03-31"},  # not YYYY-MM-DD
        {"preset": "custom", "from": "2026-02-30", "to": "2026-03-31"},  # no such day
        {"preset": "custom", "from": "1999-12-31", "to": "2026-03-31"},  # before MIN_DATE
        {"preset": "custom", "from": "2026-01-01", "to": "2101-01-01"},  # after MAX_DATE
        {"preset": "custom", "from": 20260101, "to": "2026-03-31"},
        {"preset": "this_month", "from": "2026-01-01"},  # dates only belong to custom
        {"preset": "this_month", "extra": 1},
        "this_month",
    ],
)
def test_bad_date_filters_are_rejected(raw):
    rejected(validate_date_filter, raw)


def test_the_date_limits_are_accepted():
    limits = {"preset": "custom", "from": MIN_DATE.isoformat(), "to": MAX_DATE.isoformat()}
    assert validate_date_filter(limits)["from"] == "2000-01-01"


# --- validate_filters ---------------------------------------------------------


def test_empty_filters_get_defaults():
    expected = {"date": INHERIT, "type": None, "categories": [], "merchant_contains": ""}
    assert validate_filters(None) == expected
    assert validate_filters({}) == expected


def test_type_filter():
    assert validate_filters({"type": "debit"})["type"] == "debit"
    rejected(validate_filters, {"type": "transfer"})


def test_categories_are_normalised_and_deduplicated():
    a, b = uuid.uuid4(), uuid.uuid4()
    result = validate_filters({"categories": [str(a).upper(), str(b), str(a)]})
    assert result["categories"] == [str(a), str(b)]


@pytest.mark.parametrize(
    "categories",
    [
        "not a list",
        ["not-a-uuid"],
        [123],
        [None],
        [str(uuid.uuid4())] * (MAX_CATEGORIES + 1),
    ],
)
def test_bad_categories_are_rejected(categories):
    rejected(validate_filters, {"categories": categories})


def test_merchant_text_is_trimmed_and_limited():
    assert validate_filters({"merchant_contains": "  tasty  "})["merchant_contains"] == "tasty"
    assert validate_filters({"merchant_contains": "x" * 60})["merchant_contains"] == "x" * 60
    rejected(validate_filters, {"merchant_contains": "x" * 61})
    rejected(validate_filters, {"merchant_contains": 5})


def test_unknown_filter_keys_are_rejected():
    rejected(validate_filters, {"account": "main"})
    rejected(validate_filters, "debit")


# --- validate_spec ------------------------------------------------------------


def full(**override):
    base = enc(
        chart="line",
        x={"field": "date", "granularity": "month"},
        color={"field": "txn_type"},
        filters={"type": "debit", "merchant_contains": " tasty "},
        stacked=True,
        orientation="horizontal",
    )
    base.update(override)
    return base


def test_validate_spec_returns_the_clean_shape():
    spec = validate_spec(full())
    assert spec["v"] == 1
    assert spec["chart"] == "line"
    assert spec["filters"] == {
        "date": INHERIT,
        "type": "debit",
        "categories": [],
        "merchant_contains": "tasty",
    }
    assert spec["stacked"] is True
    assert spec["orientation"] == "horizontal"


def test_validate_spec_defaults_for_the_presentation_options():
    spec = validate_spec(enc())
    assert spec["stacked"] is False
    assert spec["orientation"] == "vertical"
    assert spec["filters"]["date"] == INHERIT


@pytest.mark.parametrize(
    "raw",
    [
        full(),
        enc(),
        {"chart": "kpi", "y": {"measure": "net"}, "compare": True},
        {"chart": "histogram", "y": {"measure": "spend", "agg": "avg"}, "bins": 8},
        enc(filters={"date": {"preset": "custom", "from": "2026-01-01", "to": "2026-02-01"}}),
        enc(filters={"categories": [str(uuid.uuid4()).upper()]}),
    ],
)
def test_validating_twice_changes_nothing(raw):
    once = validate_spec(raw)
    assert validate_spec(once) == once


def test_unknown_top_level_keys_are_rejected():
    rejected(validate_spec, full(sql="DROP TABLE"))


def test_the_spec_version_is_checked():
    assert validate_spec(full(v=1))["v"] == 1
    rejected(validate_spec, full(v=2), code="unsupported_version")
    rejected(validate_spec, full(v=True), code="unsupported_version")


def test_validate_spec_surfaces_encoding_and_filter_errors():
    rejected(validate_spec, full(chart="radar"))
    rejected(validate_spec, full(filters={"type": "transfer"}))
    rejected(validate_spec, full(stacked="yes"))
    rejected(validate_spec, full(orientation="diagonal"))
    rejected(validate_spec, [])
    rejected(validate_spec, None)


# --- resolve_period -----------------------------------------------------------


@pytest.mark.parametrize(
    "preset, expected",
    [
        ("this_month", (date(2026, 10, 1), TODAY)),
        ("last_month", (date(2026, 9, 1), date(2026, 9, 30))),
        ("last_3_months", (date(2026, 8, 1), TODAY)),
        ("last_12_months", (date(2025, 11, 1), TODAY)),
        ("this_year", (date(2026, 1, 1), TODAY)),
        ("all", (MIN_DATE, TODAY)),
    ],
)
def test_presets_resolve_to_dates(preset, expected):
    assert resolve_period({"preset": preset}, INHERIT, TODAY) == expected


def test_last_month_in_january_is_december_of_the_previous_year():
    assert resolve_period({"preset": "last_month"}, INHERIT, date(2026, 1, 15)) == (
        date(2025, 12, 1),
        date(2025, 12, 31),
    )


def test_last_3_months_can_start_in_the_previous_year():
    start, _ = resolve_period({"preset": "last_3_months"}, INHERIT, date(2026, 2, 10))
    assert start == date(2025, 12, 1)


def test_custom_dates_are_used_as_given():
    custom = {"preset": "custom", "from": "2026-01-05", "to": "2026-02-10"}
    assert resolve_period(custom, INHERIT, TODAY) == (date(2026, 1, 5), date(2026, 2, 10))


def test_a_panel_preset_wins_over_the_dashboard_preset():
    result = resolve_period({"preset": "this_year"}, {"preset": "this_month"}, TODAY)
    assert result == (date(2026, 1, 1), TODAY)


def test_inherit_uses_the_dashboard_preset():
    assert resolve_period(INHERIT, {"preset": "this_month"}, TODAY) == (date(2026, 10, 1), TODAY)


def test_inherit_all_the_way_up_uses_the_default_preset():
    assert DEFAULT_PRESET == "last_3_months"
    assert resolve_period(INHERIT, INHERIT, TODAY) == (date(2026, 8, 1), TODAY)

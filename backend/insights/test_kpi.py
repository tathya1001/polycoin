"""KPI cards: comparisons, sparkline, secondary figures, and the version 2 -> 3 upgrade."""

from datetime import date
from decimal import Decimal

import pytest

from insights import services
from insights.engine import comparison_periods, load_start, run
from insights.spec import (
    AVERAGE_OF_RANGE,
    MAX_SECONDARY,
    SpecError,
    catalogue,
    upgrade,
    validate_spec,
)
from transactions.tests import make_txn, make_user

D = Decimal
PERIOD = (date(2026, 3, 1), date(2026, 3, 31))


def row(day: date, amount: str, txn_type: str = "debit", category: str = "Food") -> dict:
    return {
        "date": day,
        "txn_type": txn_type,
        "category_name": category,
        "amount": D(amount),
        "name": "",
        "balance": None,
    }


def kpi(measure="spend", **options):
    """A validated KPI spec with the given `kpi` options."""
    return validate_spec({"chart": "kpi", "y": {"measure": measure}, "kpi": options})


def first_row(result):
    return result["rows"][0]


# --- validation ----------------------------------------------------------------------


def test_a_kpi_gets_every_option_filled_in():
    assert kpi()["kpi"] == {
        "compare": "none",
        "sparkline": None,
        "direction": "auto",
        "secondary": [],
    }
    assert validate_spec({"chart": "kpi", "y": {"measure": "spend"}})["kpi"]["compare"] == "none"


def test_the_average_comparison_has_a_number_of_periods_and_no_other_does():
    assert kpi(compare="average")["kpi"]["average_of"] == 3
    assert kpi(compare="average", average_of=6)["kpi"]["average_of"] == 6
    assert "average_of" not in kpi(compare="previous")["kpi"]
    with pytest.raises(SpecError):
        kpi(compare="previous", average_of=6)


def test_a_clean_kpi_validates_to_itself():
    once = kpi(compare="average", average_of=4, sparkline="day", secondary=["count", "average"])
    assert validate_spec(once) == once


@pytest.mark.parametrize(
    "options",
    [
        {"compare": "last_week"},
        {"compare": True},
        {"compare": "average", "average_of": 2},
        {"compare": "average", "average_of": AVERAGE_OF_RANGE[1] + 1},
        {"compare": "average", "average_of": True},
        {"sparkline": "hour"},
        {"direction": "sideways"},
        {"secondary": "count"},
        {"secondary": ["median"]},
        {"secondary": ["count", "count"]},
        {"secondary": ["count"] * (MAX_SECONDARY + 1)},
        {"surprise": 1},
    ],
)
def test_impossible_kpi_options_are_refused(options):
    with pytest.raises(SpecError):
        kpi(**options)


def test_money_figures_need_a_money_measure_and_the_share_needs_a_sum():
    for measure in ("count", "balance"):
        with pytest.raises(SpecError):
            kpi(measure, secondary=["average"])
        with pytest.raises(SpecError):
            kpi(measure, secondary=["largest"])
    assert kpi("count", secondary=["count"])["kpi"]["secondary"] == ["count"]
    with pytest.raises(SpecError):
        validate_spec(
            {
                "chart": "kpi",
                "y": {"measure": "spend", "agg": "avg"},
                "kpi": {"secondary": ["share_of_income"]},
            }
        )


def test_only_a_kpi_has_kpi_options():
    with pytest.raises(SpecError):
        validate_spec(
            {"chart": "bar", "x": {"field": "category"}, "y": {"measure": "spend"}, "kpi": {}}
        )
    assert "kpi" not in validate_spec(
        {"chart": "bar", "x": {"field": "category"}, "y": {"measure": "spend"}}
    )


def test_the_catalogue_describes_the_kpi_options():
    options = catalogue()["kpi"]
    assert options["compares"] == ["none", "previous", "year_ago", "average"]
    assert options["average_of"] == [3, 12] and options["max_secondary"] == 3
    share = next(f for f in options["secondary"] if f["id"] == "share_of_income")
    assert share == {"id": "share_of_income", "needs_money_measure": True, "needs_sum": True}


# --- the upgrade from compare: true ----------------------------------------------------


@pytest.mark.parametrize("version", [1, 2])
def test_compare_true_becomes_the_previous_period(version):
    old = {"v": version, "chart": "kpi", "y": {"measure": "spend"}, "compare": True}
    assert validate_spec(old)["kpi"]["compare"] == "previous"
    assert "compare" not in validate_spec(old)


@pytest.mark.parametrize("compare", [False, None])
def test_compare_false_becomes_no_comparison(compare):
    old = {"v": 1, "chart": "kpi", "y": {"measure": "spend"}, "compare": compare}
    assert validate_spec(old)["kpi"]["compare"] == "none"


def test_old_compare_keeps_its_old_errors():
    for old in (
        {"v": 1, "chart": "kpi", "y": {"measure": "spend"}, "compare": "yes"},
        {
            "v": 1,
            "chart": "bar",
            "x": {"field": "category"},
            "y": {"measure": "spend"},
            "compare": True,
        },
        {"v": 2, "chart": "kpi", "y": {"measure": "spend"}, "kpi": {}},
    ):
        with pytest.raises(SpecError):
            upgrade(old)
    # compare: false on a chart is harmless, as it always was.
    bar = {
        "v": 1,
        "chart": "bar",
        "x": {"field": "category"},
        "y": {"measure": "spend"},
        "compare": False,
    }
    assert "compare" not in validate_spec(bar)


# --- comparison periods and loading ---------------------------------------------------------


def test_each_comparison_names_its_periods():
    assert comparison_periods({"compare": "none"}, PERIOD) == []
    assert comparison_periods({"compare": "previous"}, PERIOD) == [
        (date(2026, 1, 29), date(2026, 2, 28))
    ]
    assert comparison_periods({"compare": "year_ago"}, PERIOD) == [
        (date(2025, 3, 1), date(2025, 3, 31))
    ]
    assert comparison_periods({"compare": "average", "average_of": 3}, PERIOD) == [
        (date(2026, 1, 29), date(2026, 2, 28)),
        (date(2025, 12, 29), date(2026, 1, 28)),
        (date(2025, 11, 28), date(2025, 12, 28)),
    ]


def test_a_kpi_loads_back_to_the_start_of_its_earliest_comparison():
    assert load_start(kpi(), PERIOD) == date(2026, 3, 1)
    assert load_start(kpi(compare="previous"), PERIOD) == date(2026, 1, 29)
    assert load_start(kpi(compare="year_ago"), PERIOD) == date(2025, 3, 1)
    assert load_start(kpi(compare="average", average_of=3), PERIOD) == date(2025, 11, 28)


# --- the numbers ---------------------------------------------------------------------


def test_compare_with_a_year_ago():
    rows = [row(date(2025, 3, 10), "100"), row(date(2026, 3, 10), "150")]
    assert first_row(run(kpi(compare="year_ago"), rows, PERIOD)) == ["150.00", "100.00", "50.0"]


def test_compare_with_the_average_of_earlier_periods():
    rows = [
        row(date(2026, 3, 10), "300"),
        row(date(2026, 2, 10), "100"),  # in the period 1 before
        row(date(2026, 1, 10), "200"),  # in the period 2 before
        # nothing in the period 3 before: a sum counts as 0 there
    ]
    spec = kpi(compare="average", average_of=3)
    assert first_row(run(spec, rows, PERIOD)) == ["300.00", "100.00", "200.0"]


def test_an_average_of_counts_shows_a_decimal_but_one_periods_count_does_not():
    rows = [row(date(2026, 3, 10), "1"), row(date(2026, 2, 10), "1"), row(date(2026, 2, 11), "1")]
    averaged = kpi("count", compare="average", average_of=3)
    assert first_row(run(averaged, rows, PERIOD))[:2] == ["1", "0.7"]
    previous = kpi("count", compare="previous")
    assert first_row(run(previous, rows, PERIOD))[:2] == ["1", "2"]


def test_no_comparison_leaves_previous_and_change_empty():
    rows = [row(date(2026, 3, 10), "10"), row(date(2026, 2, 10), "99")]
    assert first_row(run(kpi(), rows, PERIOD)) == ["10.00", None, None]


def test_the_sparkline_is_the_value_over_time_inside_the_period():
    rows = [row(date(2026, 3, 2), "10"), row(date(2026, 3, 2), "5"), row(date(2026, 3, 9), "7")]
    result = run(kpi(sparkline="week"), rows, PERIOD)
    assert result["sparkline"] == {
        "granularity": "week",
        "columns": ["x", "value"],
        "rows": [
            ["2026-02-23", "0.00"],
            ["2026-03-02", "15.00"],
            ["2026-03-09", "7.00"],
            ["2026-03-16", "0.00"],
            ["2026-03-23", "0.00"],
            ["2026-03-30", "0.00"],
        ],
    }
    assert "sparkline" not in run(kpi(), rows, PERIOD)


def test_secondary_figures():
    rows = [
        row(date(2026, 3, 2), "10"),
        row(date(2026, 3, 3), "30"),
        row(date(2026, 3, 4), "20"),
        row(date(2026, 3, 5), "500", "credit"),
    ]
    spec = kpi(secondary=["count", "average", "largest"])
    figures = {f["id"]: f["value"] for f in run(spec, rows, PERIOD)["secondary"]}
    assert figures == {"count": "3", "average": "20.00", "largest": "30.00"}  # debits only


def test_the_share_of_income_uses_rows_the_panels_type_filter_removed():
    debits = [row(date(2026, 3, 2), "250")]
    everything = [*debits, row(date(2026, 3, 1), "1000", "credit")]
    spec = kpi(secondary=["share_of_income"])
    figure = run(spec, debits, PERIOD, all_types=everything)["secondary"][0]
    assert figure == {"id": "share_of_income", "value": "25.0"}
    # Without the other types there is no income to compare with.
    assert run(spec, debits, PERIOD)["secondary"][0]["value"] is None


def test_secondary_figures_with_nothing_to_show_are_empty_not_zero():
    figures = run(kpi(secondary=["average", "largest", "count"]), [], PERIOD)["secondary"]
    assert figures == [
        {"id": "average", "value": None},
        {"id": "largest", "value": None},
        {"id": "count", "value": "0"},
    ]


# --- through the batch ---------------------------------------------------------------------


@pytest.mark.django_db
def test_a_debit_only_kpi_still_shows_its_share_of_income():
    alice = make_user("alice@example.com")
    make_txn(alice, date=date(2026, 3, 5), amount=D("200.00"), description="a")
    make_txn(alice, date=date(2026, 3, 6), txn_type="credit", amount=D("800.00"), description="b")
    panel = {
        "chart": "kpi",
        "y": {"measure": "spend"},
        "kpi": {"secondary": ["share_of_income", "count"]},
        "filters": {"type": "debit"},  # the panel's own filter hides the credit row
    }
    filters = {"date": {"preset": "custom", "from": "2026-03-01", "to": "2026-03-31"}}

    result = services.run_queries(
        alice, filters, [{"key": "k", "spec": panel}], today=date(2026, 4, 1)
    )

    assert first_row(result["k"]) == ["200.00", None, None]
    assert result["k"]["secondary"] == [
        {"id": "share_of_income", "value": "25.0"},
        {"id": "count", "value": "1"},
    ]


@pytest.mark.django_db
def test_a_year_ago_kpi_loads_last_years_rows():
    alice = make_user("alice@example.com")
    make_txn(alice, date=date(2025, 3, 10), amount=D("100.00"), description="a")
    make_txn(alice, date=date(2026, 3, 10), amount=D("120.00"), description="b")
    panel = {"chart": "kpi", "y": {"measure": "spend"}, "kpi": {"compare": "year_ago"}}
    filters = {"date": {"preset": "custom", "from": "2026-03-01", "to": "2026-03-31"}}

    result = services.run_queries(
        alice, filters, [{"key": "k", "spec": panel}], today=date(2026, 4, 1)
    )

    assert first_row(result["k"]) == ["120.00", "100.00", "20.0"]

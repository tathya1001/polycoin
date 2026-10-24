"""Table calculations: running total, % of total, moving average and change."""

from datetime import date
from decimal import Decimal

import pytest

from insights import services
from insights.engine import (
    change,
    load_start,
    moving_average,
    run,
    running_total,
    share,
    year_before,
)
from insights.spec import DEFAULT_WINDOW, SpecError, catalogue, validate_spec
from transactions.tests import make_txn, make_user

D = Decimal


def row(day: date, amount: str, category: str = "Food", txn_type: str = "debit") -> dict:
    return {
        "date": day,
        "txn_type": txn_type,
        "category_name": category,
        "amount": D(amount),
        "name": "",
        "balance": None,
    }


def spec(**override) -> dict:
    base = {
        "chart": "line",
        "x": {"field": "date", "granularity": "month"},
        "y": {"measure": "spend"},
    }
    base.update(override)
    return validate_spec(base)


def values(result: dict) -> list:
    return [r[-1] for r in result["rows"]]


Q1 = (date(2026, 1, 1), date(2026, 3, 31))


# --- the pure calculations --------------------------------------------------------


def test_running_total_adds_up_in_order_and_counts_an_empty_bucket_as_zero():
    assert running_total([D(10), None, D(5)]) == [D(10), D(10), D(15)]


def test_moving_average_skips_unknown_values_and_needs_at_least_one():
    assert moving_average([D(3), D(6), D(9), D(12)], 3) == [D(3), D("4.5"), D(6), D(9)]
    assert moving_average([None, D(4), None], 2) == [None, D(4), D(4)]
    assert moving_average([None, None], 2) == [None, None]


def test_change_as_an_amount_or_a_percent_and_never_a_percent_of_nothing():
    assert change([D(150), D(90)], [D(100), D(100)], "amount") == [D(50), D(-10)]
    assert change([D(150), D(90)], [D(100), D(-100)], "percent") == [D(50), D(190)]
    assert change([D(5), D(5), None], [D(0), None, D(1)], "percent") == [None, None, None]


def test_share_is_a_percentage_of_a_nonzero_total():
    assert share(D(25), D(200)) == D("12.5")
    assert share(D(25), D(0)) is None
    assert share(None, D(10)) is None


def test_year_before_keeps_the_day_and_moves_29_february_to_the_28th():
    assert year_before(date(2026, 3, 15)) == date(2025, 3, 15)
    assert year_before(date(2024, 2, 29)) == date(2023, 2, 28)


# --- how far back a panel loads --------------------------------------------------


@pytest.mark.parametrize(
    "calc, expected",
    [
        (None, date(2026, 1, 1)),
        ({"type": "running_total"}, date(2026, 1, 1)),
        ({"type": "percent_of_total"}, date(2026, 1, 1)),
        ({"type": "moving_average", "window": 3}, date(2025, 11, 1)),  # two months before
        ({"type": "change", "vs": "previous"}, date(2025, 12, 1)),  # one month before
        ({"type": "change", "vs": "year_ago"}, date(2025, 1, 1)),
    ],
)
def test_load_start_reaches_back_only_as_far_as_the_calculation_needs(calc, expected):
    assert load_start(spec(calc=calc), Q1) == expected


def test_a_weekly_year_ago_change_loads_from_the_week_containing_that_day():
    weekly = spec(
        x={"field": "date", "granularity": "week"}, calc={"type": "change", "vs": "year_ago"}
    )
    assert load_start(weekly, (date(2026, 1, 7), date(2026, 3, 31))) == date(2024, 12, 30)


def test_a_comparing_kpi_still_loads_the_previous_period():
    kpi = validate_spec({"chart": "kpi", "y": {"measure": "spend"}, "kpi": {"compare": "previous"}})
    assert load_start(kpi, Q1) == date(2025, 10, 3)


# --- the calculations on a chart ---------------------------------------------------


def test_running_total_by_month():
    rows = [row(date(2026, 1, 5), "10"), row(date(2026, 2, 5), "20"), row(date(2026, 3, 5), "30")]
    result = run(spec(calc={"type": "running_total"}), rows, Q1)
    assert values(result) == ["10.00", "30.00", "60.00"]
    assert result["meta"]["calc"] == {"type": "running_total"}


def test_a_moving_average_uses_the_months_before_the_period_but_does_not_show_them():
    rows = [row(date(2025, 11, 5), "30"), row(date(2025, 12, 5), "60"), row(date(2026, 1, 5), "90")]
    result = run(spec(calc={"type": "moving_average", "window": 3}), rows, Q1)
    assert [r[0] for r in result["rows"]] == ["2026-01-01", "2026-02-01", "2026-03-01"]
    assert values(result) == ["60.00", "50.00", "30.00"]


def test_change_vs_the_previous_month_includes_the_month_before_the_period():
    rows = [row(date(2025, 12, 5), "100"), row(date(2026, 1, 5), "150")]
    result = run(spec(calc={"type": "change"}), rows, (date(2026, 1, 1), date(2026, 2, 28)))
    assert values(result) == ["50.0", "-100.0"]  # percent by default


def test_change_as_an_amount_keeps_the_measures_format():
    rows = [row(date(2026, 1, 5), "100"), row(date(2026, 2, 5), "120.50")]
    result = run(
        spec(calc={"type": "change", "as": "amount"}), rows, (date(2026, 1, 1), date(2026, 2, 28))
    )
    assert values(result) == ["100.00", "20.50"]


def test_change_vs_a_year_ago():
    rows = [row(date(2025, 1, 10), "100"), row(date(2026, 1, 10), "120")]
    result = run(
        spec(calc={"type": "change", "vs": "year_ago"}), rows, (date(2026, 1, 1), date(2026, 1, 31))
    )
    assert result["rows"] == [["2026-01-01", "20.0"]]


def test_percent_of_total_without_a_split_is_each_values_share_of_the_chart():
    rows = [row(date(2026, 1, 5), "30", "Food"), row(date(2026, 1, 6), "70", "Bills")]
    bar = spec(chart="bar", x={"field": "category"}, calc={"type": "percent_of_total"})
    assert run(bar, rows, Q1)["rows"] == [["Bills", "70.0"], ["Food", "30.0"]]


def test_percent_of_total_includes_the_folded_other():
    rows = [row(date(2026, 1, 5), "30", "Food"), row(date(2026, 1, 6), "70", "Bills")]
    bar = spec(chart="bar", x={"field": "category"}, limit=1, calc={"type": "percent_of_total"})
    assert run(bar, rows, Q1)["rows"] == [["Bills", "70.0"], ["Other", "30.0"]]


def test_percent_of_total_with_a_split_is_each_segments_share_of_its_bar():
    rows = [
        row(date(2026, 1, 5), "25", txn_type="debit"),
        row(date(2026, 1, 6), "75", txn_type="credit"),
        row(date(2026, 2, 5), "10", txn_type="debit"),
    ]
    bar = spec(
        chart="bar",
        y={"measure": "amount"},
        color={"field": "txn_type"},
        calc={"type": "percent_of_total"},
    )
    result = run(bar, rows, (date(2026, 1, 1), date(2026, 2, 28)))
    assert result["rows"] == [
        ["2026-01-01", "credit", "75.0"],
        ["2026-01-01", "debit", "25.0"],
        ["2026-02-01", "credit", "0.0"],
        ["2026-02-01", "debit", "100.0"],
    ]


def test_a_running_total_runs_separately_for_each_colour():
    rows = [
        row(date(2026, 1, 5), "10", "Food"),
        row(date(2026, 2, 5), "5", "Food"),
        row(date(2026, 1, 9), "1", "Bills"),
    ]
    split = spec(color={"field": "category"}, calc={"type": "running_total"})
    result = run(split, rows, (date(2026, 1, 1), date(2026, 2, 28)))
    assert result["rows"] == [
        ["2026-01-01", "Bills", "1.00"],
        ["2026-01-01", "Food", "10.00"],
        ["2026-02-01", "Bills", "1.00"],
        ["2026-02-01", "Food", "15.00"],
    ]


def test_a_moving_average_of_an_average_skips_empty_months():
    rows = [row(date(2026, 1, 5), "10"), row(date(2026, 1, 9), "30"), row(date(2026, 3, 5), "40")]
    avg = spec(y={"measure": "spend", "agg": "avg"}, calc={"type": "moving_average", "window": 2})
    assert values(run(avg, rows, Q1)) == ["20.00", "20.00", "40.00"]


def test_a_moving_average_of_counts_keeps_its_decimals():
    rows = [row(date(2026, 1, 5), "1"), row(date(2026, 1, 6), "1"), row(date(2026, 2, 5), "1")]
    counts = spec(y={"measure": "count"}, calc={"type": "moving_average", "window": 2})
    # January averages in December (the lookback month), which has no transactions: (0 + 2) / 2.
    assert values(run(counts, rows, Q1)) == ["1.00", "1.50", "0.50"]


# --- validation --------------------------------------------------------------------


def test_defaults_are_filled_in_and_a_clean_calc_round_trips():
    assert spec(calc={"type": "moving_average"})["calc"] == {
        "type": "moving_average",
        "window": DEFAULT_WINDOW,
    }
    full = spec(calc={"type": "change"})
    assert full["calc"] == {"type": "change", "vs": "previous", "as": "percent"}
    assert validate_spec(full) == full


def test_no_calc_means_no_calc_key():
    assert "calc" not in spec()
    assert "calc" not in spec(calc=None)


@pytest.mark.parametrize(
    "override",
    [
        {"chart": "kpi", "x": None, "calc": {"type": "running_total"}},
        {"chart": "histogram", "x": None, "calc": {"type": "percent_of_total"}},
        {"chart": "bar", "x": {"field": "category"}, "calc": {"type": "running_total"}},
        {"chart": "bar", "x": {"field": "weekday"}, "calc": {"type": "change"}},
        {"y": {"measure": "spend", "agg": "avg"}, "calc": {"type": "running_total"}},
        {"y": {"measure": "net"}, "calc": {"type": "percent_of_total"}},
        {"calc": {"type": "moving_average", "window": 1}},
        {"calc": {"type": "moving_average", "window": 13}},
        {"calc": {"type": "moving_average", "window": True}},
        {"calc": {"type": "running_total", "window": 3}},
        {"calc": {"type": "running_total", "vs": "previous"}},
        {"calc": {"type": "change", "vs": "last_week"}},
        {"calc": {"type": "change", "as": "ratio"}},
        {"calc": {"type": "rank"}},
        {"calc": {"type": "running_total", "extra": 1}},
        {"calc": "running_total"},
    ],
)
def test_impossible_calculations_are_refused(override):
    raw = {
        "chart": "line",
        "x": {"field": "date", "granularity": "month"},
        "y": {"measure": "spend"},
    }
    raw.update({k: v for k, v in override.items() if v is not None})
    for key in [k for k, v in override.items() if v is None]:
        raw.pop(key, None)
    with pytest.raises(SpecError):
        validate_spec(raw)


def test_the_catalogue_lists_each_calculation_and_its_rules():
    calcs = {c["id"]: c for c in catalogue()["calcs"]}
    assert calcs["running_total"] == {
        "id": "running_total",
        "needs_date": True,
        "additive_only": True,
        "never_negative": False,
    }
    assert calcs["percent_of_total"]["needs_date"] is False
    assert catalogue()["limits"]["window"] == [2, 12]
    assert catalogue()["change_vs"] == ["previous", "year_ago"]


# --- through the batch, with the database -------------------------------------------


@pytest.mark.django_db
def test_a_year_ago_change_loads_last_years_rows_in_the_batch():
    alice = make_user("alice@example.com")
    make_txn(alice, date=date(2025, 1, 10), amount=D("100.00"), description="a")
    make_txn(alice, date=date(2026, 1, 10), amount=D("120.00"), description="b")
    panel = {
        "chart": "bar",
        "x": {"field": "date", "granularity": "month"},
        "y": {"measure": "spend"},
        "calc": {"type": "change", "vs": "year_ago"},
    }
    filters = {"date": {"preset": "custom", "from": "2026-01-01", "to": "2026-01-31"}}

    results = services.run_queries(
        alice, filters, [{"key": "p", "spec": panel}], today=date(2026, 2, 1)
    )

    assert results["p"]["rows"] == [["2026-01-01", "20.0"]]
    assert results["p"]["period"] == {"from": "2026-01-01", "to": "2026-01-31"}

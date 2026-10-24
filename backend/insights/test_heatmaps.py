"""The calendar heatmap (one cell per day) and the matrix heatmap (two fields)."""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from insights import services
from insights.engine import CALENDAR_MAX_DAYS, PeriodTooLong, run
from insights.spec import CALENDAR_MAX_DAYS as SPEC_CALENDAR_MAX_DAYS
from insights.spec import SpecError, catalogue, validate_spec
from transactions.tests import make_txn, make_user

D = Decimal
MARCH = (date(2026, 3, 1), date(2026, 3, 31))


def row(day: date, amount: str, category: str = "Food", txn_type: str = "debit") -> dict:
    return {
        "date": day,
        "txn_type": txn_type,
        "category_name": category,
        "amount": D(amount),
        "name": "",
        "balance": None,
    }


def calendar(**override):
    return validate_spec({"chart": "calendar", "y": {"measure": "spend"}, **override})


def matrix(x=None, rows="category", **override):
    spec = {
        "chart": "heatmap",
        "x": x or {"field": "weekday"},
        "rows": {"field": rows},
        "y": {"measure": "spend"},
    }
    return validate_spec({**spec, **override})


# --- validation ------------------------------------------------------------------------


def test_the_two_limits_agree():
    assert CALENDAR_MAX_DAYS == SPEC_CALENDAR_MAX_DAYS == 366


def test_a_calendar_has_a_measure_and_nothing_else_to_pick():
    spec = calendar()
    assert spec["chart"] == "calendar" and "x" not in spec and "rows" not in spec
    assert spec["format"] == {
        "labels": False,
        "number": "auto",
        "legend": "auto",
        "axis": {"min": None, "max": None},
    }
    assert validate_spec(spec) == spec


@pytest.mark.parametrize(
    "extra",
    [
        {"x": {"field": "category"}},
        {"color": {"field": "category"}},
        {"rows": {"field": "category"}},
        {"calc": {"type": "running_total"}},
        {"format": {"legend": "top"}},
        {"format": {"axis": {"min": 0}}},
    ],
)
def test_a_calendar_refuses_what_it_cannot_use(extra):
    with pytest.raises(SpecError):
        calendar(**extra)


def test_a_heatmap_needs_two_different_fields():
    spec = matrix()
    assert spec["x"] == {"field": "weekday"} and spec["rows"] == {"field": "category"}
    assert validate_spec(spec) == spec
    assert matrix(x={"field": "date", "granularity": "month"})["x"]["granularity"] == "month"


@pytest.mark.parametrize(
    "bad",
    [
        {"rows": None},  # no rows at all
        {"rows": {"field": "weekday"}},  # the same as x
        {"rows": {"field": "date"}},  # rows can't be time buckets
        {"rows": {"field": "colour"}},
        {"rows": {"field": "category", "extra": 1}},
        {"color": {"field": "txn_type"}},
        {"calc": {"type": "percent_of_total"}},
        {"format": {"legend": "top"}},
    ],
)
def test_impossible_heatmaps_are_refused(bad):
    raw = {
        "chart": "heatmap",
        "x": {"field": "weekday"},
        "rows": {"field": "category"},
        "y": {"measure": "spend"},
    }
    raw.update(bad)
    if raw["rows"] is None:
        del raw["rows"]
    with pytest.raises(SpecError):
        validate_spec(raw)


def test_only_a_heatmap_has_rows():
    bar = {"chart": "bar", "x": {"field": "category"}, "y": {"measure": "spend"}}
    with pytest.raises(SpecError):
        validate_spec({**bar, "rows": {"field": "weekday"}})


def test_older_specs_upgrade_untouched():
    old = {"v": 4, "chart": "bar", "x": {"field": "category"}, "y": {"measure": "spend"}}
    assert "rows" not in validate_spec(old)


def test_the_catalogue_offers_both_charts():
    offered = catalogue()
    assert "calendar" in offered["charts"] and "heatmap" in offered["charts"]
    assert offered["rows_fields"] == [
        "weekday",
        "month_of_year",
        "category",
        "txn_type",
        "merchant",
    ]
    assert offered["limits"]["calendar_days"] == 366


# --- the calendar ------------------------------------------------------------------------


def test_a_calendar_has_a_value_for_each_day_that_has_transactions():
    rows = [row(date(2026, 3, 2), "10"), row(date(2026, 3, 2), "5"), row(date(2026, 3, 9), "7")]
    result = run(calendar(), rows, MARCH)
    assert result["columns"] == ["x", "value"]
    assert result["rows"] == [
        ["2026-03-02", "15.00"],
        ["2026-03-09", "7.00"],
    ]  # blank days left out
    assert result["meta"]["range"] == ["2026-03-01", "2026-03-31"]


def test_a_calendar_ignores_rows_outside_its_period_and_the_wrong_type():
    rows = [
        row(date(2026, 2, 28), "99"),
        row(date(2026, 3, 1), "10"),
        row(date(2026, 3, 1), "500", txn_type="credit"),
        row(date(2026, 4, 1), "99"),
    ]
    assert run(calendar(), rows, MARCH)["rows"] == [["2026-03-01", "10.00"]]


def test_a_calendar_can_use_any_measure_and_aggregation():
    rows = [row(date(2026, 3, 2), "10"), row(date(2026, 3, 2), "30")]
    average = calendar(y={"measure": "spend", "agg": "avg"})
    assert run(average, rows, MARCH)["rows"] == [["2026-03-02", "20.00"]]
    count = calendar(y={"measure": "count"})
    assert run(count, rows, MARCH)["rows"] == [["2026-03-02", "2"]]


def test_a_calendar_of_more_than_a_year_is_refused():
    start = date(2026, 1, 1)
    run(calendar(), [], (start, start + timedelta(days=365)))  # exactly 366 days: fine
    with pytest.raises(PeriodTooLong):
        run(calendar(), [], (start, start + timedelta(days=366)))


# --- the matrix ---------------------------------------------------------------------------


def test_a_matrix_has_a_cell_for_each_pair_that_has_transactions():
    rows = [
        row(date(2026, 3, 2), "10", "Food"),  # a Monday
        row(date(2026, 3, 2), "5", "Food"),
        row(date(2026, 3, 3), "7", "Bills"),  # a Tuesday
        row(date(2026, 3, 9), "20", "Food"),  # the next Monday
    ]
    result = run(matrix(), rows, MARCH)
    assert result["columns"] == ["x", "row", "value"]
    assert result["axes"]["x"] == [0, 1, 2, 3, 4, 5, 6]  # every weekday, Monday first
    assert result["axes"]["rows"] == ["Food", "Bills"]  # biggest first
    assert result["rows"] == [[0, "Food", "35.00"], [1, "Bills", "7.00"]]  # sparse, left to right
    assert result["meta"]["rows"] == {"field": "category"}


def test_matrix_axes_cover_the_whole_range_even_where_nothing_happened():
    rows = [row(date(2026, 3, 5), "10")]
    months = run(matrix(x={"field": "month_of_year"}, rows="txn_type"), rows, MARCH)
    assert months["axes"]["x"] == list(range(1, 13))
    by_week = run(matrix(x={"field": "date", "granularity": "week"}), rows, MARCH)
    assert by_week["axes"]["x"][0] == "2026-02-23" and len(by_week["axes"]["x"]) == 6


def test_categorical_axes_keep_the_biggest_few_without_an_other_cell():
    rows = [row(date(2026, 3, 2), str(amount), f"Cat{amount}") for amount in (50, 40, 30, 20)]
    result = run(matrix(limit=2), rows, MARCH)
    assert result["axes"]["rows"] == ["Cat50", "Cat40"]
    assert all(cell[1] in ("Cat50", "Cat40") for cell in result["rows"])


def test_categorical_axes_can_be_sorted_by_name():
    rows = [row(date(2026, 3, 2), "50", "Zeta"), row(date(2026, 3, 2), "10", "Alpha")]
    assert run(matrix(sort="label"), rows, MARCH)["axes"]["rows"] == ["Alpha", "Zeta"]


def test_a_matrix_of_nothing_is_empty_but_still_has_axes():
    result = run(matrix(), [], MARCH)
    assert (
        result["rows"] == []
        and result["axes"]["x"] == list(range(7))
        and result["axes"]["rows"] == []
    )


# --- through the batch ----------------------------------------------------------------------


@pytest.mark.django_db
def test_the_batch_runs_both_charts_and_reports_a_too_long_calendar():
    alice = make_user("alice@example.com")
    make_txn(alice, date=date(2026, 3, 5), amount=D("40.00"), description="a")
    queries = [
        {"key": "cal", "spec": {"chart": "calendar", "y": {"measure": "spend"}}},
        {
            "key": "map",
            "spec": {
                "chart": "heatmap",
                "x": {"field": "weekday"},
                "rows": {"field": "category"},
                "y": {"measure": "spend"},
            },
        },
    ]
    filters = {"date": {"preset": "custom", "from": "2026-03-01", "to": "2026-03-31"}}
    results = services.run_queries(alice, filters, queries, today=date(2026, 4, 1))
    assert results["cal"]["rows"] == [["2026-03-05", "40.00"]]
    assert results["map"]["rows"][0][2] == "40.00"

    wide = {"date": {"preset": "custom", "from": "2024-01-01", "to": "2026-03-31"}}
    too_long = services.run_queries(alice, wide, queries[:1], today=date(2026, 4, 1))
    assert too_long["cal"]["error"] == {
        "code": "period_too_long",
        "detail": "Pick a period of a year or less.",
    }

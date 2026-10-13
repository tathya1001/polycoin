from datetime import date, timedelta
from decimal import Decimal

import pytest

from insights.engine import (
    MAX_BUCKETS,
    OTHER_LABEL,
    TooManyBuckets,
    add_months,
    aggregate,
    bucket_date,
    bucket_range,
    dimension_key,
    group_rows,
    histogram,
    measure_value,
    next_bucket,
    previous_period,
    run,
    run_grouped,
    top_n,
)


def test_day_is_unchanged():
    assert bucket_date(date(2026, 10, 11), "day") == date(2026, 10, 11)


def test_week_starts_on_monday():
    assert bucket_date(date(2026, 10, 11), "week") == date(2026, 10, 5)  # a Sunday
    assert bucket_date(date(2026, 10, 5), "week") == date(2026, 10, 5)   # already a Monday


def test_week_can_start_in_the_previous_year():
    assert bucket_date(date(2026, 1, 1), "week") == date(2025, 12, 29)


def test_month_is_the_first_of_the_month():
    assert bucket_date(date(2026, 10, 31), "month") == date(2026, 10, 1)


@pytest.mark.parametrize(
    "d, expected",
    [
        (date(2026, 1, 15), date(2026, 1, 1)),
        (date(2026, 3, 31), date(2026, 1, 1)),
        (date(2026, 4, 1), date(2026, 4, 1)),
        (date(2026, 12, 31), date(2026, 10, 1)),
    ],
)
def test_quarter_is_the_first_day_of_its_quarter(d, expected):
    assert bucket_date(d, "quarter") == expected


def test_year_is_january_first():
    assert bucket_date(date(2026, 10, 11), "year") == date(2026, 1, 1)


def test_unknown_granularity_raises():
    with pytest.raises(ValueError):
        bucket_date(date(2026, 1, 1), "fortnight")


def test_next_bucket_crosses_a_year_end():
    assert next_bucket(date(2026, 12, 1), "month") == date(2027, 1, 1)
    assert next_bucket(date(2026, 10, 1), "quarter") == date(2027, 1, 1)
    assert next_bucket(date(2026, 1, 1), "year") == date(2027, 1, 1)


def test_next_bucket_for_days_and_weeks():
    assert next_bucket(date(2026, 2, 28), "day") == date(2026, 3, 1)
    assert next_bucket(date(2026, 10, 5), "week") == date(2026, 10, 12)


def test_bucket_range_snaps_both_ends_to_their_buckets():
    assert bucket_range(date(2026, 10, 15), date(2026, 12, 3), "month") == [
        date(2026, 10, 1),
        date(2026, 11, 1),
        date(2026, 12, 1),
    ]


def test_bucket_range_includes_months_with_no_data_in_between():
    months = bucket_range(date(2026, 1, 20), date(2026, 4, 2), "month")
    assert len(months) == 4  # Jan, Feb, Mar, Apr


def test_bucket_range_within_one_bucket_is_a_single_item():
    assert bucket_range(date(2026, 10, 3), date(2026, 10, 28), "month") == [date(2026, 10, 1)]


def test_bucket_range_with_end_before_start_is_empty():
    assert bucket_range(date(2026, 10, 10), date(2026, 10, 1), "day") == []


def test_bucket_range_by_week():
    assert bucket_range(date(2026, 10, 1), date(2026, 10, 14), "week") == [
        date(2026, 9, 28),
        date(2026, 10, 5),
        date(2026, 10, 12),
    ]


def row(amount, txn_type="debit", balance=None):
    return {"amount": Decimal(amount), "txn_type": txn_type, "balance": balance}


# --- measure_value ------------------------------------------------------------


def test_spend_counts_only_debits():
    assert measure_value(row("450.00", "debit"), "spend") == Decimal("450.00")
    assert measure_value(row("450.00", "credit"), "spend") is None


def test_income_counts_only_credits():
    assert measure_value(row("900.00", "credit"), "income") == Decimal("900.00")
    assert measure_value(row("900.00", "debit"), "income") is None


def test_net_is_signed():
    assert measure_value(row("100", "credit"), "net") == Decimal("100")
    assert measure_value(row("100", "debit"), "net") == Decimal("-100")


def test_count_is_one_per_row_and_amount_ignores_direction():
    assert measure_value(row("5", "debit"), "count") == 1
    assert measure_value(row("5", "credit"), "amount") == Decimal("5")


def test_balance_passes_through_and_may_be_missing():
    assert measure_value(row("5", balance=Decimal("1000")), "balance") == Decimal("1000")
    assert measure_value(row("5", balance=None), "balance") is None


def test_unknown_measure_raises():
    with pytest.raises(ValueError):
        measure_value(row("5"), "profit")


# --- aggregate ----------------------------------------------------------------


def test_sum_is_exact_with_decimals():
    # floats would give 0.30000000000000004
    assert aggregate([Decimal("0.10")] * 3, "sum") == Decimal("0.30")


def test_avg_min_max_last():
    values = [Decimal("10"), Decimal("20"), Decimal("60")]
    assert aggregate(values, "avg") == Decimal("30")
    assert aggregate(values, "min") == Decimal("10")
    assert aggregate(values, "max") == Decimal("60")
    assert aggregate(values, "last") == Decimal("60")


def test_median_of_odd_and_even_counts():
    assert aggregate([Decimal("5"), Decimal("1"), Decimal("3")], "median") == Decimal("3")
    even = [Decimal("1"), Decimal("2"), Decimal("3"), Decimal("10")]
    assert aggregate(even, "median") == Decimal("2.5")


def test_count_counts_values():
    assert aggregate([Decimal("7"), Decimal("7")], "count") == 2


def test_empty_input():
    assert aggregate([], "sum") == 0
    assert aggregate([], "count") == 0
    for agg in ("avg", "min", "max", "median", "last"):
        assert aggregate([], agg) is None


def test_unknown_aggregation_raises_even_for_empty_input():
    with pytest.raises(ValueError):
        aggregate([], "averge")


def txn(d, name="TASTYBITES", category="Food", txn_type="debit", amount="10"):
    return {
        "date": d,
        "name": name,
        "category_name": category,
        "txn_type": txn_type,
        "amount": Decimal(amount),
        "balance": None,
    }


# --- dimension_key ------------------------------------------------------------


def test_date_dimension_uses_the_granularity():
    r = txn(date(2026, 10, 11))
    assert dimension_key(r, "date", "month") == date(2026, 10, 1)
    assert dimension_key(r, "date", "week") == date(2026, 10, 5)


def test_date_dimension_without_a_granularity_raises():
    with pytest.raises(ValueError):
        dimension_key(txn(date(2026, 10, 11)), "date")


def test_weekday_and_month_of_year_ignore_the_year():
    assert dimension_key(txn(date(2026, 10, 11)), "weekday") == 6  # Sunday
    assert dimension_key(txn(date(2026, 10, 12)), "weekday") == 0  # Monday
    assert dimension_key(txn(date(2025, 10, 3)), "month_of_year") == dimension_key(
        txn(date(2026, 10, 3)), "month_of_year"
    )


def test_category_and_type_dimensions():
    r = txn(date(2026, 1, 1), category="Rent", txn_type="credit")
    assert dimension_key(r, "category") == "Rent"
    assert dimension_key(r, "txn_type") == "credit"


def test_merchant_ignores_case_and_extra_spaces():
    keys = {
        dimension_key(txn(date(2026, 1, 1), name=n), "merchant")
        for n in ("TASTYBITES", "tastybites ", "Tastybites", "  tastybites")
    }
    assert keys == {"Tastybites"}


def test_unknown_dimension_raises():
    with pytest.raises(ValueError):
        dimension_key(txn(date(2026, 1, 1)), "colour")


# --- group_rows ---------------------------------------------------------------


def test_group_by_one_dimension():
    rows = [
        txn(date(2026, 10, 1), category="Food"),
        txn(date(2026, 10, 2), category="Rent"),
        txn(date(2026, 10, 3), category="Food"),
    ]
    groups = group_rows(rows, [("category", None)])
    assert list(groups) == [("Food",), ("Rent",)]  # first-seen order
    assert len(groups[("Food",)]) == 2


def test_group_by_two_dimensions_makes_tuple_keys():
    rows = [
        txn(date(2026, 10, 1), category="Food", txn_type="debit"),
        txn(date(2026, 10, 9), category="Food", txn_type="credit"),
        txn(date(2026, 11, 2), category="Food", txn_type="debit"),
    ]
    groups = group_rows(rows, [("date", "month"), ("txn_type", None)])
    assert set(groups) == {
        (date(2026, 10, 1), "debit"),
        (date(2026, 10, 1), "credit"),
        (date(2026, 11, 1), "debit"),
    }


def test_no_dimensions_gives_a_single_group_of_everything():
    rows = [txn(date(2026, 10, 1)), txn(date(2026, 10, 2))]
    groups = group_rows(rows, [])
    assert list(groups) == [()]
    assert len(groups[()]) == 2


def test_no_rows_gives_no_groups():
    assert group_rows([], [("category", None)]) == {}


D = Decimal


# --- top_n --------------------------------------------------------------------


def test_top_n_keeps_the_largest_and_folds_the_rest_into_other():
    pairs = [("a", D(5)), ("b", D(9)), ("c", D(1)), ("d", D(3))]
    assert top_n(pairs, 2) == [("b", D(9)), ("a", D(5)), (OTHER_LABEL, D(4))]


def test_top_n_total_is_unchanged_by_folding():
    pairs = [(str(i), D(i)) for i in range(1, 11)]
    assert sum(value for _, value in top_n(pairs, 3)) == sum(value for _, value in pairs)


def test_top_n_adds_no_other_when_everything_fits():
    pairs = [("a", D(1)), ("b", D(2))]
    assert top_n(pairs, 2) == [("b", D(2)), ("a", D(1))]
    assert top_n(pairs, 10) == [("b", D(2)), ("a", D(1))]


def test_top_n_without_fold_just_drops_the_rest():
    pairs = [("a", D(5)), ("b", D(9)), ("c", D(1))]
    assert top_n(pairs, 2, fold=False) == [("b", D(9)), ("a", D(5))]


def test_top_n_ties_keep_input_order():
    assert top_n([("x", D(1)), ("y", D(1))], 1, fold=False) == [("x", D(1))]


def test_top_n_needs_a_positive_n():
    with pytest.raises(ValueError):
        top_n([("a", D(1))], 0)


# --- histogram ----------------------------------------------------------------


def test_histogram_bins_and_counts():
    values = [D(v) for v in range(1, 11)]  # 1..10
    assert histogram(values, 3) == [(D(1), D(4), 3), (D(4), D(7), 3), (D(7), D(10), 4)]


def test_histogram_counts_add_up_and_the_maximum_is_included():
    values = [D(0), D(4), D(5), D(10)]
    bins = histogram(values, 2)
    assert bins == [(D(0), D(5), 2), (D(5), D(10), 2)]
    assert sum(count for _, _, count in bins) == len(values)


def test_histogram_with_one_unique_value_is_a_single_bin():
    assert histogram([D(500), D(500), D(500)], 10) == [(D(500), D(500), 3)]


def test_histogram_of_nothing_is_empty():
    assert histogram([], 5) == []


def test_histogram_needs_at_least_one_bin():
    with pytest.raises(ValueError):
        histogram([D(1)], 0)


PERIOD = (date(2026, 1, 1), date(2026, 3, 31))


def deal(d, category, txn_type, amount, name="SHOP"):
    return txn(d, name=name, category=category, txn_type=txn_type, amount=amount)


ROWS = [
    deal(date(2026, 1, 10), "Food", "debit", "100"),
    deal(date(2026, 1, 20), "Food", "debit", "50"),
    deal(date(2026, 1, 25), "Rent", "debit", "800"),
    deal(date(2026, 3, 5), "Food", "debit", "30"),
    deal(date(2026, 3, 6), "Salary", "credit", "1000"),
]


def make_spec(**override):
    base = {
        "chart": "bar",
        "x": {"field": "category"},
        "y": {"measure": "spend", "agg": "sum"},
        "limit": 10,
    }
    base.update(override)
    return base


def test_bar_spend_by_category_ranks_largest_first_and_skips_credits():
    result = run_grouped(make_spec(), ROWS, PERIOD)
    assert result["columns"] == ["x", "value"]
    # no Salary row: that category only has a credit
    assert result["rows"] == [["Rent", "800.00"], ["Food", "180.00"]]


def test_line_fills_empty_months_with_zero_for_totals():
    spec = make_spec(chart="line", x={"field": "date", "granularity": "month"})
    assert run_grouped(spec, ROWS, PERIOD)["rows"] == [
        ["2026-01-01", "950.00"],
        ["2026-02-01", "0.00"],
        ["2026-03-01", "30.00"],
    ]


def test_line_average_leaves_a_gap_instead_of_a_zero():
    spec = make_spec(
        chart="line",
        x={"field": "date", "granularity": "month"},
        y={"measure": "spend", "agg": "avg"},
    )
    assert run_grouped(spec, ROWS, PERIOD)["rows"] == [
        ["2026-01-01", "316.67"],
        ["2026-02-01", None],
        ["2026-03-01", "30.00"],
    ]


def test_limit_folds_the_rest_into_other():
    result = run_grouped(make_spec(limit=1), ROWS, PERIOD)
    assert result["rows"] == [["Rent", "800.00"], ["Other", "180.00"]]


def test_sort_by_label():
    result = run_grouped(make_spec(sort="label"), ROWS, PERIOD)
    assert result["rows"] == [["Food", "180.00"], ["Rent", "800.00"]]


def test_color_makes_long_rows_and_fills_missing_combinations():
    spec = make_spec(
        chart="bar", x={"field": "date", "granularity": "month"}, color={"field": "category"}
    )
    result = run_grouped(spec, ROWS, PERIOD)
    assert result["columns"] == ["x", "color", "value"]
    assert result["rows"] == [
        ["2026-01-01", "Food", "150.00"],
        ["2026-01-01", "Rent", "800.00"],
        ["2026-02-01", "Food", "0.00"],
        ["2026-02-01", "Rent", "0.00"],
        ["2026-03-01", "Food", "30.00"],
        ["2026-03-01", "Rent", "0.00"],
    ]


def test_count_measure_prints_whole_numbers():
    spec = make_spec(y={"measure": "count", "agg": "sum"})
    rows = run_grouped(spec, ROWS, PERIOD)["rows"]
    assert rows == [["Food", "3"], ["Rent", "1"], ["Salary", "1"]]


def test_weekday_axis_always_shows_all_seven_days():
    spec = make_spec(x={"field": "weekday"})
    assert run_grouped(spec, ROWS, PERIOD)["rows"] == [
        [0, "0.00"], [1, "50.00"], [2, "0.00"], [3, "30.00"],
        [4, "0.00"], [5, "100.00"], [6, "800.00"],
    ]


def test_no_rows_still_gives_a_complete_time_axis_and_an_empty_category_axis():
    line = make_spec(chart="line", x={"field": "date", "granularity": "month"})
    assert [r[1] for r in run_grouped(line, [], PERIOD)["rows"]] == ["0.00", "0.00", "0.00"]
    assert run_grouped(make_spec(), [], PERIOD)["rows"] == []


def test_previous_period_is_the_same_length_ending_the_day_before():
    march = (date(2026, 3, 1), date(2026, 3, 31))
    assert previous_period(march) == (date(2026, 1, 29), date(2026, 2, 28))
    feb_and_march = (date(2026, 2, 1), date(2026, 3, 31))
    assert previous_period(feb_and_march) == (date(2025, 12, 4), date(2026, 1, 31))


# --- kpi ----------------------------------------------------------------------


def kpi_spec(**override):
    base = {"chart": "kpi", "y": {"measure": "spend", "agg": "sum"}}
    base.update(override)
    return base


def test_kpi_is_a_single_total():
    assert run(kpi_spec(), ROWS, PERIOD)["rows"] == [["980.00", None, None]]


def test_kpi_with_compare_gives_previous_and_percent_change():
    period = (date(2026, 2, 1), date(2026, 3, 31))  # previous period is Dec 4 - Jan 31
    result = run(kpi_spec(compare=True), ROWS, period)
    assert result["rows"] == [["30.00", "950.00", "-96.8"]]


def test_kpi_percent_is_none_when_the_previous_period_is_zero():
    period = (date(2026, 3, 1), date(2026, 3, 31))  # previous period has no spend
    assert run(kpi_spec(compare=True), ROWS, period)["rows"] == [["30.00", "0.00", None]]


def test_kpi_with_no_data_is_zero_for_totals_and_unknown_for_averages():
    assert run(kpi_spec(), [], PERIOD)["rows"] == [["0.00", None, None]]
    avg = kpi_spec(y={"measure": "spend", "agg": "avg"})
    assert run(avg, [], PERIOD)["rows"] == [[None, None, None]]


# --- histogram ----------------------------------------------------------------


def test_histogram_chart_bins_spend_amounts():
    spec = {"chart": "histogram", "y": {"measure": "spend", "agg": "sum"}, "bins": 2}
    result = run(spec, ROWS, PERIOD)
    assert result["columns"] == ["start", "end", "count"]
    assert result["rows"] == [["30.00", "415.00", 3], ["415.00", "800.00", 1]]


# --- run ----------------------------------------------------------------------


def test_run_ignores_rows_outside_the_period():
    january = (date(2026, 1, 1), date(2026, 1, 31))
    assert run(make_spec(), ROWS, january)["rows"] == [["Rent", "800.00"], ["Food", "150.00"]]


def test_run_sorts_rows_by_date_so_last_works():
    rows = [
        {**txn(date(2026, 1, 20)), "balance": Decimal("700")},
        {**txn(date(2026, 1, 5)), "balance": Decimal("1000")},  # given out of order on purpose
    ]
    spec = make_spec(
        chart="line",
        x={"field": "date", "granularity": "month"},
        y={"measure": "balance", "agg": "last"},
    )
    january = (date(2026, 1, 1), date(2026, 1, 31))
    assert run(spec, rows, january)["rows"] == [["2026-01-01", "700.00"]]


def test_run_rejects_an_unknown_chart():
    with pytest.raises(ValueError):
        run(make_spec(chart="radar"), ROWS, PERIOD)


# --- limits -------------------------------------------------------------------


def test_add_months_moves_forward_and_backward_across_years():
    assert add_months(date(2026, 11, 1), 3) == date(2027, 2, 1)
    assert add_months(date(2026, 2, 1), -3) == date(2025, 11, 1)
    assert add_months(date(2026, 5, 1), 0) == date(2026, 5, 1)


def test_bucket_range_allows_exactly_the_maximum_and_refuses_more():
    start = date(2026, 1, 1)
    assert len(bucket_range(start, start + timedelta(days=MAX_BUCKETS - 1), "day")) == MAX_BUCKETS
    with pytest.raises(TooManyBuckets):
        bucket_range(start, start + timedelta(days=MAX_BUCKETS), "day")


def test_too_many_buckets_is_a_value_error_so_callers_can_catch_either():
    assert issubclass(TooManyBuckets, ValueError)


def test_a_daily_line_over_many_years_is_refused_instead_of_built():
    spec = make_spec(chart="line", x={"field": "date", "granularity": "day"})
    with pytest.raises(TooManyBuckets):
        run(spec, ROWS, (date(2020, 1, 1), date(2026, 1, 1)))

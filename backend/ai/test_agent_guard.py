"""Reining a small model's reply in to what the request asked for (ai/agent/guard.py)."""

import pytest

from ai.agent.guard import (
    mentions_merchant,
    named_chart,
    named_measures,
    named_x,
    overrule_refusal,
    rein_in,
    says_nothing,
)
from ai.agent.schema import PanelIntent


def intent(**fields) -> PanelIntent:
    return PanelIntent(kind="panel", **fields)


def reined(message: str, previous: dict | None = None, **fields) -> PanelIntent:
    return rein_in(intent(**fields), message, previous)[0]


# --- keys the request doesn't support are dropped ---------------------------------------------


def test_a_calculation_nobody_asked_for_is_dropped_with_a_note():
    result, notes = rein_in(intent(chart="line", calc="running_total"), "Spend this year", None)
    assert result.calc is None
    assert notes == ["The request asks for no calculation, so none was added."]


@pytest.mark.parametrize(
    "message, calc",
    [
        ("Running total of spend this year", "running_total"),
        ("Each category's percent of total spend", "percent_of_total"),
        ("Month over month change in spend", "change"),
    ],
)
def test_a_calculation_the_request_asks_for_stays(message, calc):
    assert reined(message, calc=calc).calc == calc


def test_a_key_from_an_earlier_turn_stays_on_a_follow_up():
    previous = {"limit": 3, "x": "merchant"}
    result = reined("sort them by name", previous, x="merchant", limit=3, sort="label")
    assert (result.limit, result.sort) == (3, "label")


@pytest.mark.parametrize(
    "field, value, message",
    [
        ("limit", 10, "Spend by category"),
        ("sort", "label", "Spend by category"),
        ("txn_type", "debit", "Spend by month"),
        ("direction", "up_is_good", "Income this month"),
        ("compare", "previous", "Income this month"),
        ("color", "txn_type", "Monthly spend"),
    ],
)
def test_optional_keys_without_supporting_words_are_dropped(field, value, message):
    assert getattr(reined(message, **{field: value}), field) in (None, "none")


@pytest.mark.parametrize(
    "field, value, message",
    [
        ("limit", 5, "Top 5 merchants by spend"),
        ("sort", "label", "Merchants sorted by name"),
        ("txn_type", "debit", "Count of debit transactions by month"),
        ("compare", "year_ago", "Spend this month against the same month a year ago"),
        ("color", "category", "Monthly spend split by category"),
    ],
)
def test_optional_keys_the_request_names_stay(field, value, message):
    assert getattr(reined(message, **{field: value}), field) == value


def test_an_extra_measure_stays_only_when_named():
    assert reined("Spend vs income each month", also_measures=["income"]).also_measures == [
        "income"
    ]
    assert reined("Top 5 merchants", also_measures=["income"]).also_measures == []


# --- merchants -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "message, merchant, kept",
    [
        ("tasty spend", "tastybites", True),  # the model expanded the user's own word
        ("Spend at Tastybites Cafe", "tastybites", True),
        ("Top 5 merchants by spend last month", "Merchant 1", False),  # made up
        ("Monthly spend", "Greenleaf", False),
    ],
)
def test_a_merchant_stays_only_when_the_message_mentions_it(message, merchant, kept):
    assert mentions_merchant(message, merchant) is kept
    assert (reined(message, merchant=merchant).merchant == merchant) is kept


# --- the x axis the message names --------------------------------------------------------------


@pytest.mark.parametrize(
    "message, expected",
    [
        ("Spend by month of the year, across all years", ("month_of_year", None)),
        ("Spend by day of the week", ("weekday", None)),
        ("Daily spend this month", ("date", "day")),
        ("Largest single spend each month this year", ("date", "month")),
        ("Month over month change in spend", ("date", "month")),
        ("Monthly spend split by category", ("date", "month")),  # the split is the colour
        ("Average spend per transaction by category", ("category", None)),
        ("Top 5 merchants by spend last month", ("merchant", None)),
        ("Spend last month", None),  # "last month" is a period, not an axis
        ("make it the top 3", None),
    ],
)
def test_the_axis_a_message_names(message, expected):
    assert named_x(message) == expected


def test_a_named_axis_wins_and_a_chart_without_one_gives_way():
    result, notes = rein_in(intent(chart="kpi", measure="spend"), "Spend by day of the week", None)
    assert (result.x, result.chart) == ("weekday", None)
    assert "The request asks for weekday along the axis." in notes


def test_a_chart_the_message_names_is_kept():
    result = reined("Daily spend as a calendar", chart="calendar")
    assert result.chart == "calendar"


def test_a_split_the_message_names_becomes_the_colour():
    result = reined("Monthly spend split by category", chart="bar", x="date")
    assert (result.x, result.granularity, result.color) == ("date", "month", "category")


# --- keys the message names win ----------------------------------------------------------------


@pytest.mark.parametrize(
    "message, expected",
    [
        ("Spend vs income each month as lines", ("spend", "income")),
        ("Earnings against spending per month", ("income", "spend")),
        ("Spend, income and net by month as bars", ("spend", "income", "net")),
        ("Net income per month", ("net",)),  # one measure, not two
        ("Histogram of my spending amounts", ("spend",)),  # "amounts" of spending
        ("How many times did I spend at Tastybites?", ("count",)),  # not joined, so not shown
        ("Money in and out each month", ()),  # one amount, split by type
        ("Top 5 merchants", ()),
    ],
)
def test_the_measures_a_message_names(message, expected):
    assert named_measures(message) == expected


def test_the_named_measures_replace_the_models_in_the_named_order():
    result, notes = rein_in(
        intent(chart="line", measure="net", also_measures=["spend", "income"]),
        "Spend vs income each month as lines",
        None,
    )
    assert (result.measure, result.also_measures) == ("spend", ["income"])
    assert "The request asks for spend, so the chart shows it." in notes


def test_adding_a_measure_keeps_the_earlier_one_first():
    previous = {"measure": "spend", "also_measures": [], "x": "date"}
    result = reined("add income too", previous, measure="income", x="date")
    assert (result.measure, result.also_measures) == ("spend", ["income"])


@pytest.mark.parametrize(
    "message, chart",
    [
        ("Each category's percent of total spend, as bars", "bar"),
        ("Spend vs income each month as lines", "line"),
        ("Income and spend as an area chart", "area"),
        ("Online spend by month", None),  # "line" inside a word
        ("Bars instead of lines", None),  # two charts: left to the model
        ("Spend on my credit card", None),  # a bank card is not a KPI card
    ],
)
def test_the_chart_a_message_names(message, chart):
    assert named_chart(message) == chart


@pytest.mark.parametrize(
    "message, calc, x",
    [
        ("Running total of spend this year", "running_total", "date"),
        ("Cumulative income this year", "running_total", "date"),
        ("Share of total spending for each merchant", "percent_of_total", "merchant"),
        ("Week over week change in spending", "change", "date"),
    ],
)
def test_a_named_calculation_is_applied_with_the_axis_it_needs(message, calc, x):
    result = reined(message, chart="kpi", measure="spend")
    assert (result.calc, result.x) == (calc, x)
    assert result.chart is None or result.chart != "kpi"


def test_change_it_to_a_chart_is_not_a_calculation():
    assert reined("change it to a pie", chart="pie", x="category").calc is None


def test_a_moving_average_takes_its_window_and_step_from_the_words():
    result = reined("6 month moving average of my income", measure="income", calc="moving_average")
    assert (result.window, result.x, result.granularity) == (6, "date", "month")


@pytest.mark.parametrize(
    "message, compare",
    [
        ("Spend this month compared with last month", "previous"),
        ("Income this month versus last month", "previous"),
        ("This month's spending compared to the same month last year", "year_ago"),
        ("Spend this month against the same month a year ago", "year_ago"),
        ("How does this month's spend compare with my 3 month average?", "average"),
    ],
)
def test_a_named_comparison_makes_a_kpi_card(message, compare):
    result = reined(message, chart="line", measure="spend", x="date", granularity="month")
    assert (result.chart, result.compare, result.x) == ("kpi", compare, None)


def test_a_comparison_with_an_average_takes_its_months():
    result = reined("Spend this month against my 6 month average", chart="kpi", measure="spend")
    assert (result.compare, result.average_of) == ("average", 6)


def test_spend_vs_income_is_not_a_comparison():
    result = reined("Spend vs income each month", chart="line", measure="spend", x="date")
    assert result.compare in (None, "none") and result.chart == "line"


def test_a_chart_that_cant_show_the_named_axis_or_split_gives_way():
    result = reined("Monthly spend split by category", chart="pie", measure="spend", x="category")
    assert (result.chart, result.x, result.color) == (None, "date", "category")


def test_an_axis_only_the_model_picked_doesnt_move_the_chart():
    assert reined("Total spend this month", chart="kpi", measure="spend", x="date").chart == "kpi"


def test_stacked_by_is_a_split():
    result = reined("Monthly spending stacked by merchant", chart="bar", measure="spend")
    assert (result.x, result.color) == ("date", "merchant")


@pytest.mark.parametrize(
    "message, x, rows",
    [
        ("Heatmap of spend by merchant and day of the week", "weekday", "merchant"),
        ("Heatmap of category against day of the week", "weekday", "category"),
        ("Heatmap of spending by merchant and month of the year", "month_of_year", "merchant"),
    ],
)
def test_a_heatmap_takes_its_rows_from_the_second_field_named(message, x, rows):
    result = reined(message, chart="heatmap", measure="spend", x="weekday", rows="category")
    assert (result.x, result.rows) == (x, rows)


# --- turning a request away --------------------------------------------------------------------


@pytest.mark.parametrize(
    "message, fields",
    [
        ("How much income did I get last month?", {"chart": "kpi", "measure": "income"}),
        ("How many transactions did I make this year?", {"chart": "kpi", "measure": "count"}),
        ("Spend by day of the week", {"measure": "spend", "x": "weekday", "chart": None}),
        ("Month over month change in spend", {"measure": "spend", "x": "date"}),
    ],
)
def test_a_plain_chart_request_turned_away_is_built_anyway(message, fields):
    panel = overrule_refusal(message)
    assert panel is not None and panel.kind == "panel"
    assert {key: getattr(panel, key) for key in fields} == fields


@pytest.mark.parametrize(
    "message",
    [
        "Why did I spend so much in March?",  # a reason
        "Why was my income lower last month?",
        "Am I spending too much on food?",  # advice
        "Should I cut back on eating out?",
        "What was my single biggest purchase ever?",  # one transaction
        "Which day of the week do I spend the most on?",
        "How much tax will I owe this year?",  # names no measure
        "Move 2000 from my savings to my card",  # an action
        "Write me a poem about money",
    ],
)
def test_a_real_question_stays_turned_away(message):
    assert overrule_refusal(message) is None


def test_a_request_with_nothing_to_rein_in_is_unchanged():
    original = intent(chart="bar", measure="spend", x="category")
    result, notes = rein_in(original, "Spend by category", None)
    assert result == original and notes == []


def test_not_a_panel_is_left_alone():
    refusal = PanelIntent(kind="not_a_panel", reason="advice")
    assert rein_in(refusal, "Should I save more?", None) == (refusal, [])


# --- an empty "panel" ---------------------------------------------------------------------------


def test_a_panel_that_sets_nothing_counts_as_no_answer():
    assert says_nothing(intent(title="Why did you spend so much in March?"))
    assert not says_nothing(intent(measure="spend"))
    assert not says_nothing(PanelIntent(kind="not_a_panel"))

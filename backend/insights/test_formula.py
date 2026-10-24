"""Calculated fields: the formula language, its limits, and a formula as a panel's measure."""

import re
from datetime import date
from decimal import Decimal

import pytest

from categories.models import Category
from insights import services
from insights.engine import run
from insights.formula import (
    FORMULA,
    FUNCTIONS,
    MAX_DEPTH,
    MAX_LENGTH,
    MAX_TOKENS,
    VARIABLES,
    FormulaError,
    compile_expression,
    evaluate_rows,
    parse_once,
)
from insights.spec import (
    SPEC_VERSION,
    SpecError,
    allowed_aggs,
    apply_parameters,
    catalogue,
    upgrade,
    validate_spec,
)
from transactions.tests import make_txn, make_user

D = Decimal
PERIOD = (date(2026, 3, 1), date(2026, 3, 31))


def row(amount: str, txn_type: str = "debit", day: int = 5, category: str = "Food") -> dict:
    return {
        "date": date(2026, 3, day),
        "txn_type": txn_type,
        "category_name": category,
        "amount": D(amount),
        "name": "",
        "balance": None,
    }


ROWS = [row("30"), row("20"), row("100", "credit")]  # spend 50, income 100, net 50, count 3


def value(text: str, rows=ROWS):
    return evaluate_rows(text, rows)


# --- the language -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("spend", "50"),
        ("income", "100"),
        ("net", "50"),
        ("count", "3"),
        ("income - spend", "50"),
        ("(income - spend) / income * 100", "50"),
        ("1 + 2 * 3", "7"),
        ("(1 + 2) * 3", "9"),
        ("10 - 4 - 3", "3"),  # left to right
        ("100 / 10 / 5", "2"),
        ("-spend", "-50"),
        ("- -spend", "50"),
        ("abs(spend - income)", "50"),
        ("abs(-3)", "3"),
        ("min(spend, income)", "50"),
        ("max(spend, income)", "100"),
        ("max(min(1, 2), 0)", "1"),
        ("2.5 * 4", "10"),
        ("spend*2", "100"),
        ("  spend   +  income ", "150"),
    ],
)
def test_the_language_does_arithmetic(text, expected):
    assert value(text) == D(expected)


def test_division_keeps_the_decimals():
    assert round(value("spend / count"), 4) == D("16.6667")


def test_it_uses_decimals_so_money_adds_up_exactly():
    rows = [row("0.1"), row("0.2")]
    assert value("spend", rows) == D("0.3")


def test_dividing_by_zero_gives_no_value_not_an_error():
    assert value("spend / 0") is None
    assert value("income / (income - income)") is None
    only_spend = [row("10")]
    assert value("spend / income", only_spend) is None
    assert value("max(1, spend / income)", only_spend) is None  # it spreads through functions
    assert value("1 + spend / income", only_spend) is None
    assert value("-(spend / income)", only_spend) is None


def test_a_result_too_large_to_show_gives_no_value():
    assert value("999999999999 * 999999999999 * 999999999999") is None


def test_the_names_cover_both_kinds_of_transaction():
    rows = [row("30", "debit"), row("100", "credit")]
    assert evaluate_rows("net", rows) == D("70")
    assert evaluate_rows("count", []) == D("0")


@pytest.mark.parametrize(
    ("text", "complaint"),
    [
        ("", "empty"),
        ("   ", "empty"),
        ("spnd", "Unknown name 'spnd' at position 1"),
        ("income - bogus", "Unknown name 'bogus' at position 10"),
        ("os.system('x')", "Unexpected character '.'"),
        ("__import__('os')", "Unexpected character"),
        ("spend; income", "Unexpected character ';'"),
        ("spend ** 2", "Unexpected '*'"),
        ("spend +", "ends too soon"),
        ("(spend", "Expected ')'"),
        ("spend)", "Unexpected ')'"),
        ("spend income", "Unexpected 'income'"),
        ("+spend", "Unexpected '+'"),
        ("abs()", "Unexpected ')'"),
        ("abs(1, 2)", "takes 1"),
        ("min(1)", "takes 2"),
        ("round(spend)", "Unknown function 'round'"),
        ("spend(1)", "Unknown function 'spend'"),
        ("income = 5", "Unexpected character '='"),
        ("'text'", "Unexpected character"),
        ("1e5", "Unexpected 'e5'"),
        ("0x10", "Unexpected 'x10'"),
        ("1.", "Unexpected character '.'"),
        ("1234567890123", "longer than 12 digits"),
        ("spend @ 2", "Unexpected character '@'"),
    ],
)
def test_a_bad_formula_is_refused_with_a_reason(text, complaint):
    with pytest.raises(FormulaError, match=re.escape(complaint)):
        compile_expression(text)


def test_nothing_but_the_language_can_run():
    # The names of Python things are not variables, and nothing is looked up by name at run time.
    for dangerous in ("__builtins__", "open", "eval", "exec", "globals", "self", "True"):
        with pytest.raises(FormulaError):
            compile_expression(dangerous)


def test_a_formula_may_not_be_longer_than_the_limit():
    compile_expression("1 + " * 20 + "1")
    with pytest.raises(FormulaError, match=str(MAX_LENGTH)):
        compile_expression("1" * (MAX_LENGTH + 1))


def test_a_formula_may_not_have_too_many_parts():
    compile_expression("+".join(["1"] * (MAX_TOKENS // 2)))
    with pytest.raises(FormulaError, match=str(MAX_TOKENS)):
        compile_expression("+".join(["1"] * MAX_TOKENS))


def test_brackets_may_not_nest_too_deep():
    ok = "(" * MAX_DEPTH + "1" + ")" * MAX_DEPTH
    assert evaluate_rows(ok, ROWS) == D(1)
    too_deep = "(" * (MAX_DEPTH + 1) + "1" + ")" * (MAX_DEPTH + 1)
    with pytest.raises(FormulaError, match="nests"):
        compile_expression(too_deep)


def test_minus_signs_and_calls_count_towards_the_depth():
    with pytest.raises(FormulaError, match="nests"):
        compile_expression("-" * (MAX_DEPTH + 1) + "1")
    with pytest.raises(FormulaError, match="nests"):
        compile_expression("abs(" * (MAX_DEPTH + 1) + "1" + ")" * (MAX_DEPTH + 1))


def test_a_huge_formula_is_refused_before_it_can_exhaust_the_stack():
    # 100000 brackets would overflow Python's recursion limit if the parser ever saw them.
    with pytest.raises(FormulaError):
        compile_expression("(" * 100_000)


def test_a_formula_is_parsed_once_per_run_and_not_kept_after_it():
    with parse_once():
        assert compile_expression("spend + 1") is compile_expression("spend + 1")
    # Outside a run nothing is cached, so no user's formula stays in memory.
    assert compile_expression("spend + 1") is not compile_expression("spend + 1")


def test_runs_do_not_share_parsed_formulas():
    with parse_once():
        first = compile_expression("spend + 1")
    with parse_once():
        assert compile_expression("spend + 1") is not first


def test_a_bad_formula_is_not_remembered_as_good():
    with parse_once():
        for _ in range(2):
            with pytest.raises(FormulaError):
                compile_expression("spnd")


def test_text_that_is_not_a_string_is_refused_before_any_lookup():
    with parse_once():
        with pytest.raises(FormulaError, match="must be text"):
            compile_expression(["spend"])


def test_the_names_and_functions_are_listed():
    assert VARIABLES == ("spend", "income", "net", "count")
    assert FUNCTIONS == {"abs": 1, "min": 2, "max": 2}


# --- as a panel's measure ------------------------------------------------------------------------


def formula_spec(expression="(income - spend) / income * 100", chart="bar", **extra):
    base = {
        "chart": chart,
        "y": {"measure": FORMULA, "formula": {"expression": expression, "as": "percent"}},
    }
    if chart == "bar":
        base["x"] = {"field": "category"}
    if chart in ("line", "area"):
        base["x"] = {"field": "date", "granularity": "day"}
    return {**base, **extra}


def test_a_formula_panel_validates_and_fills_in_defaults():
    clean = validate_spec(formula_spec())
    assert clean["y"] == {
        "measure": "formula",
        "agg": "avg",
        "formula": {"expression": "(income - spend) / income * 100", "as": "percent"},
    }
    assert validate_spec(clean) == clean


def test_the_formula_is_tidied_and_the_form_defaults_to_number():
    spec = formula_spec("  income   -  spend ")
    spec["y"]["formula"].pop("as")
    assert validate_spec(spec)["y"]["formula"] == {"expression": "income - spend", "as": "number"}


@pytest.mark.parametrize("chart", ["bar", "line", "area", "kpi"])
def test_a_formula_works_on_grouped_charts_and_kpis(chart):
    assert validate_spec(formula_spec(chart=chart))["y"]["measure"] == "formula"


@pytest.mark.parametrize("chart", ["pie", "donut", "histogram", "calendar"])
def test_a_formula_is_refused_on_other_charts(chart):
    spec = {"chart": chart, "y": formula_spec()["y"]}
    if chart in ("pie", "donut"):
        spec["x"] = {"field": "category"}
    with pytest.raises(SpecError, match="calculated field works on"):
        validate_spec(spec)


def test_the_heatmap_is_refused_too():
    spec = {**formula_spec(chart="bar"), "chart": "heatmap", "rows": {"field": "txn_type"}}
    with pytest.raises(SpecError, match="calculated field works on"):
        validate_spec(spec)


@pytest.mark.parametrize(
    "y",
    [
        {"measure": "formula"},
        {"measure": "formula", "formula": None},
        {"measure": "formula", "formula": {}},
        {"measure": "formula", "formula": {"expression": 5}},
        {"measure": "formula", "formula": {"expression": "spnd"}},
        {"measure": "formula", "formula": {"expression": "spend", "as": "words"}},
        {"measure": "formula", "formula": {"expression": "spend", "extra": 1}},
        {"measure": "formula", "agg": "sum", "formula": {"expression": "spend"}},
        {"measure": "spend", "formula": {"expression": "spend"}},
    ],
)
def test_a_broken_formula_spec_is_refused(y):
    with pytest.raises(SpecError):
        validate_spec({"chart": "bar", "x": {"field": "category"}, "y": y})


def test_the_error_says_what_is_wrong_with_the_formula():
    with pytest.raises(SpecError) as caught:
        validate_spec(formula_spec("income - bogus"))
    assert caught.value.code == "invalid_spec"
    assert "Unknown name 'bogus'" in caught.value.detail


def test_only_one_aggregation_applies_to_a_formula():
    assert allowed_aggs(FORMULA) == ("avg",)


def test_a_formula_panel_cannot_follow_the_measure_parameter():
    spec = formula_spec()
    spec["bind"] = {"measure": "measure"}
    with pytest.raises(SpecError, match="no measure to follow"):
        validate_spec(spec)


def test_the_other_parameters_still_work_on_a_formula_panel():
    spec = formula_spec(chart="line")
    spec["bind"] = {"granularity": "granularity"}
    applied = apply_parameters(
        validate_spec(spec),
        {"top_n": 10, "granularity": "week", "measure": "net", "comparison": "previous"},
    )
    assert applied["x"]["granularity"] == "week"
    assert applied["y"]["measure"] == "formula"


def test_a_running_total_or_share_of_a_formula_is_refused_but_a_moving_average_is_not():
    for kind in ("running_total", "percent_of_total"):
        with pytest.raises(SpecError):
            validate_spec({**formula_spec(chart="line"), "calc": {"type": kind}})
    ok = validate_spec(
        {**formula_spec(chart="line"), "calc": {"type": "moving_average", "window": 3}}
    )
    assert ok["calc"]["type"] == "moving_average"


def test_a_kpi_formula_cannot_have_a_money_figure_under_it():
    spec = {"chart": "kpi", "y": formula_spec()["y"], "kpi": {"secondary": ["largest"]}}
    with pytest.raises(SpecError):
        validate_spec(spec)


def test_the_catalogue_describes_the_language_for_the_editor():
    formula = catalogue()["formula"]
    assert formula["variables"] == list(VARIABLES)
    assert formula["functions"] == {"abs": 1, "min": 2, "max": 2}
    assert formula["charts"] == ["bar", "line", "area", "kpi"]
    assert formula["agg"] == "avg"
    assert formula["forms"] == ["number", "percent", "money"]
    assert formula["max_length"] == MAX_LENGTH


def test_a_version_six_spec_still_loads():
    old = {"v": 6, "chart": "bar", "x": {"field": "category"}, "y": {"measure": "spend"}}
    assert upgrade(old)["v"] == SPEC_VERSION == 7
    assert validate_spec(old)["y"] == {"measure": "spend", "agg": "sum"}


# --- the engine ----------------------------------------------------------------------------------


def test_a_formula_bar_chart_gives_one_value_per_group():
    rows = [
        row("40", category="Food"),
        row("60", "credit", category="Food"),
        row("10", category="Rent"),
        row("30", "credit", category="Rent"),
    ]
    result = run(validate_spec(formula_spec()), rows, PERIOD)
    assert dict(map(tuple, result["rows"])) == {"Rent": "66.67", "Food": "33.33"}


def test_a_group_without_an_answer_is_left_out_not_shown_as_zero():
    rows = [row("40", category="Food"), row("10", "credit", category="Rent")]  # Food has no income
    result = run(validate_spec(formula_spec()), rows, PERIOD)
    assert {label for label, _ in result["rows"]} == {"Rent"}


def test_an_empty_time_bucket_stays_empty_instead_of_zero():
    rows = [
        row("40", day=2),
        row("100", "credit", day=2),
        row("30", day=4),
        row("60", "credit", day=4),
    ]
    spec = validate_spec(formula_spec(chart="line"))
    result = run(spec, rows, (date(2026, 3, 1), date(2026, 3, 5)))
    by_day = {label: value for label, value in result["rows"]}
    assert by_day["2026-03-02"] == "60.00"
    assert by_day["2026-03-03"] is None  # nothing happened that day: no rate, not 0%
    assert by_day["2026-03-04"] == "50.00"


def test_a_formula_bar_chart_does_not_fold_the_rest_into_other():
    rows = []
    for index in range(4):
        rows += [row("10", category=f"C{index}"), row("20", "credit", category=f"C{index}")]
    spec = validate_spec({**formula_spec(), "limit": 2})
    labels = [label for label, _ in run(spec, rows, PERIOD)["rows"]]
    assert len(labels) == 2 and "Other" not in labels  # a rate of the rest would mean nothing


def test_a_formula_kpi_shows_the_value_for_the_whole_period():
    spec = validate_spec({"chart": "kpi", "y": formula_spec()["y"]})
    assert run(spec, ROWS, PERIOD)["rows"][0][0] == "50.00"


def test_a_formula_kpi_compares_with_the_previous_period():
    spec = validate_spec({"chart": "kpi", "y": formula_spec()["y"], "kpi": {"compare": "previous"}})
    earlier = [
        {**row("80"), "date": date(2026, 2, 10)},
        {**row("100", "credit"), "date": date(2026, 2, 10)},
    ]
    result = run(spec, earlier + ROWS, PERIOD)
    assert result["rows"][0][:2] == ["50.00", "20.00"]


def test_a_formula_with_no_transactions_gives_no_value():
    spec = validate_spec({"chart": "kpi", "y": formula_spec()["y"]})
    assert run(spec, [], PERIOD)["rows"][0][0] is None


# --- through the service and the endpoint --------------------------------------------------------------


@pytest.fixture
def alice(db):
    user = make_user("alice@example.com")
    for day, amount, kind, category in (
        (5, "40", "debit", "Food"),
        (6, "60", "credit", "Salary"),
        (7, "20", "debit", "Rent"),
    ):
        make_txn(
            user,
            date=date(2026, 3, day),
            amount=D(amount),
            txn_type=kind,
            name=f"n{day}",
            description=f"d{day}",
            category=Category.objects.get(user=user, name=category),
        )
    return user


MARCH = {"date": {"preset": "custom", "from": "2026-03-01", "to": "2026-03-31"}}


def test_a_formula_panel_runs_through_the_batch(alice):
    kpi = {"chart": "kpi", "y": formula_spec()["y"]}
    results = services.run_queries(
        alice, MARCH, [{"key": "k", "spec": kpi}], today=date(2026, 4, 1)
    )
    assert results["k"]["rows"][0][0] == "0.00"  # income 60, spend 60: nothing saved


def test_a_bad_formula_breaks_one_panel_not_the_batch(alice):
    bad = {"chart": "kpi", "y": {"measure": "formula", "formula": {"expression": "spnd"}}}
    good = {"chart": "kpi", "y": {"measure": "spend"}}
    results = services.run_queries(
        alice,
        MARCH,
        [{"key": "bad", "spec": bad}, {"key": "good", "spec": good}],
        today=date(2026, 4, 1),
    )
    assert results["bad"]["error"]["code"] == "invalid_spec"
    assert results["good"]["rows"][0][0] == "60.00"


def test_the_rows_behind_a_formula_panel_are_every_transaction(alice):
    kpi = {"chart": "kpi", "y": formula_spec()["y"]}
    body = services.list_rows(alice, MARCH, kpi, None, today=date(2026, 4, 1))
    assert body["total"] == 3
    assert {row["txn_type"] for row in body["rows"]} == {"debit", "credit"}
    assert body["value"] == "0.00"


def test_a_formula_with_a_category_mark_lists_that_categorys_rows(alice):
    bar = formula_spec()
    body = services.list_rows(alice, MARCH, bar, {"categories": ["Food"]}, today=date(2026, 4, 1))
    assert body["total"] == 1 and body["rows"][0]["category"] == "Food"

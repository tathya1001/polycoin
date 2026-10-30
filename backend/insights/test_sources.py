"""Data sources on charts: choosing them, naming them in formulas, balances, and transfers."""

from datetime import date
from decimal import Decimal

import pytest

from datasources.services import create_source, first_source, sources_for
from insights import engine, services
from insights.balances import BalanceBook, closing_row
from insights.formula import (
    FormulaError,
    compile_expression,
    evaluate_rows,
    rename_source,
    source_ref,
)
from transactions.models import TransferLink
from transactions.tests import make_txn, make_user
from vault.services import UserCipher

D = Decimal
TODAY = date(2026, 4, 1)
MARCH = {"date": {"preset": "custom", "from": "2026-03-01", "to": "2026-03-31"}}
KPI = {"chart": "kpi", "y": {"measure": "spend"}}
BAR = {"chart": "bar", "x": {"field": "data_source"}, "y": {"measure": "spend"}}


def row(kind="debit", amount="10.00", source="oakbank", name="OakBank", **extra) -> dict:
    return {
        "date": date(2026, 3, 1),
        "txn_type": kind,
        "amount": D(amount),
        "balance": None,
        "category_name": "Food",
        "source_key": source,
        "source_name": name,
        **extra,
    }


def value(text: str, rows: list[dict]):
    return evaluate_rows(text, rows)


# --- the formula language ------------------------------------------------------------------------


ROWS = [
    row(amount="100.00"),
    row("credit", "40.00"),
    row(amount="7.00", source="oak salary", name="Oak Salary"),
    row("credit", "3.00", source="oak salary", name="Oak Salary"),
]


@pytest.mark.parametrize(
    "text, expected",
    [
        ("OakBank.spend", "100"),
        ("oakbank.SPEND", "100"),
        ("OakBank.income", "40"),
        ("OakBank.net", "-60"),
        ("OakBank.count", "2"),
        ("[Oak Salary].spend", "7"),
        ("[ oak   salary ].income", "3"),
        ("OakBank.spend - [Oak Salary].income", "97"),
        ("spend", "107"),  # a bare name still means everything in the group
        ('OakBank.SUM(IF [Type] = "debit" THEN [Amount] END)', "100"),
        ("[Oak Salary].COUNT([Amount])", "2"),
        ('SUM(IF [Data Source] = "Oak Salary" THEN [Amount] END)', "10"),
        ("1.5 + 2.5", "4"),  # a dot inside a number is still a number
    ],
)
def test_a_formula_can_name_a_source(text, expected):
    assert value(text, ROWS) == D(expected)


def test_a_source_with_no_rows_in_the_group_is_zero():
    assert value("RiverBank.spend", ROWS) == 0


@pytest.mark.parametrize(
    "text, reason",
    [
        ("OakBank.days", "After a data source"),
        ("OakBank.unknown", "After a data source"),
        ("OakBank.ABS(1)", "After a data source"),
        ("OakBank.MIN(1, 2)", "takes 1 value"),
        ("OakBank.", "After a data source"),
        ("[].spend", "has no name"),
        ("[Amount].__class__", "After a data source"),
        ("SUM(OakBank.spend)", "cannot contain another aggregate"),
    ],
)
def test_a_bad_reference_is_refused_with_a_reason(text, reason):
    with pytest.raises(FormulaError, match=reason):
        compile_expression(text)


def test_a_formula_lists_the_sources_it_names():
    compiled = compile_expression("OakBank.spend + [Oak  Salary].income + OAKBANK.net")
    assert compiled.sources == {"oakbank", "oak salary"}


@pytest.mark.parametrize(
    "name, written",
    [
        ("OakBank", "OakBank"),
        ("Oak Salary", "[Oak Salary]"),
        ("2024 Savings", "[2024 Savings]"),
        ("If", "[If]"),  # a keyword can't stand alone
    ],
)
def test_a_name_is_written_in_brackets_when_it_has_to_be(name, written):
    assert source_ref(name) == written


@pytest.mark.parametrize(
    "text, old, new, expected",
    [
        ("OakBank.spend - 1", "OakBank", "River", "River.spend - 1"),
        ("oakbank.spend", "OakBank", "River Bank", "[River Bank].spend"),
        ("[Oak Salary].spend + spend", "Oak Salary", "Pay", "Pay.spend + spend"),
        ("OakBank.spend + OakBank.income", "OakBank", "A B", "[A B].spend + [A B].income"),
        ('[Category] = "OakBank.spend"', "OakBank", "River", '[Category] = "OakBank.spend"'),
        ("River.spend", "OakBank", "Pay", "River.spend"),
    ],
)
def test_renaming_a_source_rewrites_only_its_references(text, old, new, expected):
    assert rename_source(text, old, new) == expected


# --- balances ------------------------------------------------------------------------------------


def statement(*amounts_and_balances) -> list[dict]:
    return [
        {"txn_type": kind, "amount": D(amount), "balance": D(balance)}
        for kind, amount, balance in amounts_and_balances
    ]


def test_the_last_row_of_a_day_is_found_from_the_balances():
    rows = statement(("debit", "10", "90"), ("debit", "20", "70"), ("credit", "5", "75"))
    assert closing_row(rows)["balance"] == 75


def test_a_statement_listed_newest_first_gives_the_same_answer():
    rows = statement(("credit", "5", "75"), ("debit", "20", "70"), ("debit", "10", "90"))
    assert closing_row(rows)["balance"] == 75


def test_money_in_and_out_again_falls_back_to_the_row_stored_last():
    rows = statement(("credit", "10", "100"), ("debit", "10", "90"))
    assert closing_row(rows)["balance"] == 90


def test_a_day_with_no_balances_has_no_closing_row():
    assert closing_row([{"txn_type": "debit", "amount": D(1), "balance": None}]) is None


def book_rows():
    return [
        row(balance=D("100"), date=date(2026, 1, 10)),
        row(balance=D("150"), date=date(2026, 3, 10)),
        row(balance=D("40"), date=date(2026, 2, 5), source="river", name="River"),
    ]


def test_a_source_keeps_its_balance_until_a_later_row():
    book = BalanceBook(book_rows())
    assert book.of("oakbank", date(2026, 2, 28)) == 100
    assert book.of("oakbank", date(2026, 3, 10)) == 150


def test_the_total_adds_up_each_sources_latest_balance():
    book = BalanceBook(book_rows())
    assert book.at(date(2026, 1, 31)) == 100
    assert book.at(date(2026, 2, 28)) == 140
    assert book.at(date(2026, 3, 31)) == 190


def test_before_any_row_the_opening_balance_counts():
    book = BalanceBook(book_rows(), {"oakbank": D("5"), "quiet": D("7")})
    assert book.at(date(2025, 12, 31)) == 12


def test_keys_limit_the_total():
    assert BalanceBook(book_rows(), keys=["river"]).at(date(2026, 3, 31)) == 40


# --- charts --------------------------------------------------------------------------------------


@pytest.fixture
def alice(db):
    user = make_user("alice@example.com")
    cipher = UserCipher(user)
    user.oak = first_source(user)
    user.river = create_source(user, cipher, "River Bank")
    return user


def run(user, spec, filters=MARCH, **extra):
    return services.run_queries(user, filters, [{"key": "p", "spec": spec}], TODAY, **extra)["p"]


def kpi_value(user, spec=KPI, filters=MARCH, **extra):
    result = run(user, spec, filters, **extra)
    assert "error" not in result, result
    return result["rows"][0][0]


def add(user, source, amount="10.00", kind="debit", day=date(2026, 3, 5), balance=None, name=""):
    return make_txn(
        user,
        data_source=source,
        amount=D(amount),
        txn_type=kind,
        date=day,
        balance=None if balance is None else D(balance),
        description=f"{name}/{amount}/{kind}/{day}/{source.pk}",
    )


def link(user, debit, credit):
    return TransferLink.objects.create(user=user, debit=debit, credit=credit)


def with_sources(spec: dict, *sources) -> dict:
    return {**spec, "filters": {"data_sources": [str(source.pk) for source in sources]}}


def test_a_panel_can_show_one_source(alice):
    add(alice, alice.oak, "30.00")
    add(alice, alice.river, "12.00")
    assert kpi_value(alice) == "42.00"
    assert kpi_value(alice, with_sources(KPI, alice.river)) == "12.00"
    assert kpi_value(alice, with_sources(KPI, alice.oak, alice.river)) == "42.00"


def test_the_dashboard_bar_applies_when_the_panel_has_no_sources_of_its_own(alice):
    add(alice, alice.oak, "30.00")
    add(alice, alice.river, "12.00")
    bar = {**MARCH, "data_sources": [str(alice.oak.pk)]}
    assert kpi_value(alice, filters=bar) == "30.00"
    assert kpi_value(alice, with_sources(KPI, alice.river), bar) == "12.00"


def test_a_chart_can_group_by_source(alice):
    add(alice, alice.oak, "30.00")
    add(alice, alice.river, "12.00")
    rows = run(alice, BAR)["rows"]
    assert rows == [["Main", "30.00"], ["River Bank", "12.00"]]


def test_a_chart_can_colour_by_source(alice):
    add(alice, alice.oak, "30.00")
    add(alice, alice.river, "12.00")
    spec = {
        "chart": "bar",
        "x": {"field": "category"},
        "color": {"field": "data_source"},
        "y": {"measure": "spend"},
    }
    assert sorted(cells[1] for cells in run(alice, spec)["rows"]) == ["Main", "River Bank"]


def test_a_click_on_a_source_narrows_the_other_panels(alice):
    add(alice, alice.oak, "30.00")
    add(alice, alice.river, "12.00")
    assert kpi_value(alice, selection={"data_sources": ["river bank"]}) == "12.00"


def test_a_panel_on_a_deleted_source_says_so_and_never_shows_everything(alice):
    add(alice, alice.oak, "30.00")
    spec = with_sources(KPI, alice.river)
    alice.river.delete()
    assert run(alice, spec)["error"]["code"] == "unknown_data_source"


def formula(text: str, chart="kpi", **extra) -> dict:
    return {
        "chart": chart,
        "y": {"measure": "formula", "formula": {"expression": text, "as": "money"}},
        **extra,
    }


def test_a_formula_reads_the_sources_it_names(alice):
    add(alice, alice.oak, "30.00")
    add(alice, alice.river, "12.00", "credit")
    assert kpi_value(alice, formula("Main.spend - [River Bank].income")) == "18.00"


def test_an_unknown_name_is_an_error_and_never_a_silent_zero(alice):
    result = run(alice, formula("Nowhere.spend"))
    assert result["error"]["code"] == "unknown_data_source"
    assert "nowhere" in result["error"]["detail"]


def test_a_named_source_ignores_the_panels_source_filter(alice):
    add(alice, alice.oak, "30.00")
    add(alice, alice.river, "12.00")
    spec = with_sources(formula("Main.spend"), alice.river)
    assert kpi_value(alice, spec) == "30.00"


def test_a_bare_name_keeps_to_the_panels_sources(alice):
    add(alice, alice.oak, "30.00")
    add(alice, alice.river, "12.00")
    spec = with_sources(formula("Main.spend - spend"), alice.river)
    assert kpi_value(alice, spec) == "18.00"


def test_a_named_source_keeps_every_other_filter(alice):
    add(alice, alice.oak, "30.00", day=date(2026, 3, 5))
    add(alice, alice.oak, "99.00", day=date(2026, 2, 5))
    assert kpi_value(alice, formula("Main.spend")) == "30.00"


def test_the_rows_behind_a_formula_give_the_same_number(alice):
    add(alice, alice.oak, "30.00")
    add(alice, alice.river, "12.00", "credit")
    spec = formula("Main.spend - [River Bank].income", chart="bar", x={"field": "category"})
    body = services.list_rows(alice, MARCH, spec, None, today=TODAY)
    assert body["value"] == "18.00"
    assert {row["data_source"] for row in body["rows"]} == {"Main", "River Bank"}


def test_a_kpi_with_a_formula_can_show_how_many_transactions(alice):
    add(alice, alice.oak, "30.00")
    spec = formula("spend", kpi={"secondary": ["count"]})
    assert run(alice, spec)["secondary"] == [{"id": "count", "value": "1"}]


# --- transfers -----------------------------------------------------------------------------------


@pytest.fixture
def transfer(alice):
    debit = add(alice, alice.oak, "500.00", balance="1000.00", name="out")
    credit = add(alice, alice.river, "500.00", "credit", balance="700.00", name="in")
    link(alice, debit, credit)
    add(alice, alice.oak, "30.00", balance="970.00", day=date(2026, 3, 6))
    return debit, credit


def test_a_transfer_cancels_out_when_both_sides_are_in_view(alice, transfer):
    assert kpi_value(alice) == "30.00"
    income = {"chart": "kpi", "y": {"measure": "income"}}
    assert kpi_value(alice, income) == "0.00"


def test_it_also_cancels_when_a_panel_names_both_sources(alice, transfer):
    assert kpi_value(alice, with_sources(KPI, alice.oak, alice.river)) == "30.00"


def test_one_side_alone_counts(alice, transfer):
    assert kpi_value(alice, with_sources(KPI, alice.oak)) == "530.00"
    income = {"chart": "kpi", "y": {"measure": "income"}}
    assert kpi_value(alice, with_sources(income, alice.river)) == "500.00"


def test_a_transfer_that_crosses_the_end_of_a_period_still_cancels(alice):
    debit = add(alice, alice.oak, "500.00", day=date(2026, 3, 31))
    credit = add(alice, alice.river, "500.00", "credit", day=date(2026, 4, 1))
    link(alice, debit, credit)
    assert kpi_value(alice) == "0.00"


def test_a_named_source_counts_its_side(alice, transfer):
    assert kpi_value(alice, formula("Main.spend")) == "530.00"
    assert kpi_value(alice, formula("spend")) == "30.00"


def test_the_rows_dialog_agrees_with_the_bar(alice, transfer):
    body = services.list_rows(alice, MARCH, KPI, None, today=TODAY)
    assert body["value"] == "30.00"
    assert body["total"] == 1


def test_a_transfer_never_changes_a_balance(alice, transfer):
    assert kpi_value(alice, {"chart": "kpi", "y": {"measure": "balance"}}) == "1670.00"


def test_deleting_one_side_brings_the_other_back(alice, transfer):
    transfer[1].delete()
    assert kpi_value(alice) == "530.00"


# --- balance on charts ---------------------------------------------------------------------------


BALANCE_KPI = {"chart": "kpi", "y": {"measure": "balance"}}
BALANCE_LINE = {
    "chart": "line",
    "x": {"field": "date", "granularity": "month"},
    "y": {"measure": "balance"},
}
SPRING = {"date": {"preset": "custom", "from": "2026-01-01", "to": "2026-03-31"}}


@pytest.fixture
def balances(alice):
    add(alice, alice.oak, "10.00", day=date(2025, 12, 20), balance="100.00")  # before the period
    add(alice, alice.oak, "10.00", day=date(2026, 1, 20), balance="90.00")
    add(alice, alice.oak, "20.00", day=date(2026, 3, 20), balance="70.00")
    add(alice, alice.river, "5.00", day=date(2025, 11, 2), balance="500.00")  # goes quiet


def test_the_total_is_each_sources_latest_balance(alice, balances):
    assert kpi_value(alice, BALANCE_KPI, SPRING) == "570.00"


def test_one_source_shows_only_its_own(alice, balances):
    assert kpi_value(alice, with_sources(BALANCE_KPI, alice.river), SPRING) == "500.00"


def test_a_quiet_month_keeps_the_balance_and_leaves_no_gap(alice, balances):
    rows = run(alice, BALANCE_LINE, SPRING)["rows"]
    assert [value for _, value in rows] == ["590.00", "590.00", "570.00"]


def test_a_line_per_source_carries_each_one_forward(alice, balances):
    spec = {**BALANCE_LINE, "color": {"field": "data_source"}}
    rows = run(alice, spec, SPRING)["rows"]
    assert {(cells[1], cells[2]) for cells in rows} == {
        ("Main", "90.00"),
        ("Main", "70.00"),
        ("River Bank", "500.00"),
    }


def test_a_bar_per_source_shows_the_latest_balance(alice, balances):
    spec = {"chart": "bar", "x": {"field": "data_source"}, "y": {"measure": "balance"}}
    assert run(alice, spec, SPRING)["rows"] == [["River Bank", "500.00"], ["Main", "70.00"]]


def test_a_formula_can_read_balances(alice, balances):
    spec = formula("Main.balance + [River Bank].balance * 2")
    assert kpi_value(alice, spec, SPRING) == "1070.00"
    assert kpi_value(alice, formula("balance"), SPRING) == "570.00"


def test_a_comparison_reads_the_balance_at_the_end_of_the_earlier_period(alice, balances):
    spec = {**BALANCE_KPI, "kpi": {"compare": "previous"}}
    march = {"date": {"preset": "custom", "from": "2026-03-01", "to": "2026-03-31"}}
    current, previous, _ = run(alice, spec, march)["rows"][0]
    assert (current, previous) == ("570.00", "590.00")


def test_a_source_with_no_balance_column_adds_nothing(alice, balances):
    add(alice, alice.river, "1.00", day=date(2026, 3, 9))  # a row with no balance
    assert kpi_value(alice, BALANCE_KPI, SPRING) == "570.00"


def test_the_engine_still_works_without_a_book():
    rows = [row(balance=D("5"))]
    spec = {
        "chart": "kpi",
        "y": {"measure": "balance", "agg": "last"},
        "kpi": {"compare": "none", "sparkline": None, "secondary": [], "direction": "auto"},
    }
    period = (date(2026, 3, 1), date(2026, 3, 31))
    assert engine.run(spec, rows, period)["rows"][0][0] == "5.00"


def test_sources_are_read_in_one_cipher_load(alice, balances, django_assert_max_num_queries):
    with django_assert_max_num_queries(10):
        run(alice, KPI, SPRING)


def test_the_first_use_names_the_first_source(alice):
    assert [source.name for source in sources_for(alice, UserCipher(alice))][0] == "Main"

"""The formula language: fields, conditions, text and dates, missing values, `days`, and the
row fields a formula makes the server decrypt."""

import re
from datetime import date
from decimal import Decimal

import pytest

from categories.models import Category
from insights import engine, services
from insights.engine import group_days, run
from insights.formula import (
    FIELDS,
    MAX_DEPTH,
    MAX_IN_ITEMS,
    MAX_STRING,
    FormulaError,
    compile_expression,
    days_in,
    evaluate_rows,
    fields_used,
    tidy,
)
from insights.spec import validate_spec
from transactions.tests import make_txn, make_user

D = Decimal
MARCH = (date(2026, 3, 1), date(2026, 3, 31))


def row(amount, txn_type="debit", day=5, category="Food", name="Moonbeam Market", balance=None):
    return {
        "date": date(2026, 3, day),
        "txn_type": txn_type,
        "category_name": category,
        "amount": D(amount),
        "name": name,
        "balance": balance,
    }


# 2026-03-07 and 08 are a Saturday and a Sunday.
ROWS = [
    row("30", day=2, category="Food", name="moonbeam  market"),
    row("20", day=7, category="Groceries", name="Corner Grocer"),
    row("50", day=8, category="Groceries", name="Corner Grocer"),
    row("200", "credit", day=9, category="Salary", name="Zentro Works"),
]  # spend 100, income 200


def value(text, rows=ROWS, days=None):
    return evaluate_rows(text, rows, days)


# --- what a formula can say ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # aggregations over fields
        ("SUM([Spend])", "100"),
        ("SUM([Income])", "200"),
        ("SUM([Net])", "100"),
        ("SUM([Amount])", "300"),
        ("COUNT([Spend])", "3"),
        ("COUNT([Amount])", "4"),
        ("SUM(1)", "4"),
        ("AVG([Spend])", "33.33333333333333333333333333"),
        ("MEDIAN([Spend])", "30"),
        ("MIN([Spend])", "20"),
        ("MAX([Amount])", "200"),
        ("COUNTD([Category])", "3"),
        ("COUNTD([Merchant])", "3"),  # "moonbeam  market" is "Moonbeam Market"
        # conditions
        ('SUM(IF [Category] = "Groceries" THEN [Spend] END) / spend * 100', "70"),
        ('SUM(IF [Category] = "groceries" THEN [Spend] END)', "70"),  # text ignores case
        ("SUM(IF [Category] IN ('Food', 'Groceries') THEN [Spend] END)", "100"),
        ("SUM(IF [Category] NOT IN ('Food') THEN [Spend] END)", "70"),
        ("COUNT(IF [Spend] > 25 THEN 1 END)", "2"),
        ("SUM(IIF(WEEKDAY([Date]) >= 6, [Spend], 0))", "70"),
        ("SUM(IF [Amount] < 25 THEN 1 ELSEIF [Amount] < 100 THEN 2 ELSE 3 END)", "8"),
        ("SUM(CASE WHEN [Type] = 'credit' THEN [Amount] ELSE 0 END)", "200"),
        ("SUM(CASE [Category] WHEN 'Food' THEN 1 WHEN 'Salary' THEN 10 ELSE 0 END)", "11"),
        ("IF net > 0 AND income > 100 THEN 1 ELSE 0 END", "1"),
        ("IF net < 0 OR NOT (income > 100) THEN 1 ELSE 0 END", "0"),
        ("IIF(spend <> 100, 1, 2)", "2"),
        ("IIF(spend != 100, 1, 2)", "2"),  # the SQL spellings are the same
        ("IIF(spend == 100, 1, 2)", "1"),
        # text and dates
        ("SUM(IF CONTAINS([Merchant], 'GROCER') THEN [Spend] END)", "70"),
        ("SUM(IF STARTSWITH([Merchant], 'moon') THEN [Spend] END)", "30"),
        ("SUM(IF ENDSWITH([Merchant], 'works') THEN [Income] END)", "200"),
        ("SUM(IF [Date] >= DATE('2026-03-08') THEN [Amount] END)", "250"),
        ("MAX(DAY([Date]))", "9"),
        ("MIN(WEEKDAY([Date]))", "1"),  # 2 March 2026 is a Monday
        ("MAX(MONTH([Date])) + MAX(YEAR([Date]))", "2029"),
        ("MAX(QUARTER([Date]))", "1"),
        ("MAX(DATEPART('weekday', [Date]))", "7"),
        ("DATEPART('Year', DATE('2026-08-01'))", "2026"),
        # numbers
        ("ROUND(spend / 3)", "33"),
        ("ROUND(spend / 3, 2)", "33.33"),
        ("ROUND(2.5)", "3"),  # half up, not to even
        ("ROUND(-2.5)", "-3"),
        ("FLOOR(-1.5)", "-2"),
        ("CEILING(1.2)", "2"),
        ("CEIL(1.2)", "2"),
        ("POWER(2, 10)", "1024"),
        ("SQRT(16)", "4"),
        ("SIGN(-3) + SIGN(0) + SIGN(9)", "0"),
        ("MIN(spend, income, 50)", "50"),
        ("MAX(1, 2, 3)", "3"),
        ("7 % 3", "1"),
        ("-7 % 3", "-1"),  # the sign of the first number, as in SQL
        ("2 + 3 * 4 % 5", "4"),  # % binds like * and /
        # missing values
        ("ZN(AVG([Balance]))", "0"),
        ("IFNULL(AVG([Balance]), 5)", "5"),
        ("COALESCE(AVG([Balance]), NULL, 7)", "7"),
        ("IIF(ISNULL(AVG([Balance])), 1, 0)", "1"),
        ("ZN(NULLIF(spend, 100))", "0"),
        ("NULLIF(spend, 1)", "100"),
        # keywords and names do not depend on letter case
        ("sum(iif([category] = 'food', [spend], 0))", "30"),
        ("Sum([SPEND]) + Spend", "200"),
        ("SUM([ amount ])", "300"),
    ],
)
def test_the_language_works_out(text, expected):
    assert value(text) == D(expected)


def test_old_formulas_mean_what_they_meant():
    assert value("(income - spend) / income * 100") == D("50")
    assert value("abs(spend - income)") == value("ABS(spend - income)") == D("100")
    assert value("min(spend, income)") == D("100")


@pytest.mark.parametrize(
    ("text", "complaint"),
    [
        ("[Foo]", "Unknown field [Foo] at position 1. Use [Amount], [Spend]"),
        ("frob(1)", "Unknown function 'frob' at position 1"),
        ("ABS(1, 2)", "ABS() takes 1 value, not 2"),
        ("IIF(TRUE, 1)", "IIF() takes 3 values, not 2"),
        ("ROUND(1, 2, 3)", "ROUND() takes 1 or 2 values, not 3"),
        ("[Amount] + spend", "[Amount] is a value for each transaction, at position 1"),
        ("spend + [Amount]", "[Amount] is a value for each transaction, at position 9"),
        ("[Amount]", "Put it inside SUM(), AVG(), COUNT()"),
        ("IF [Spend] > 0 THEN 1 END", "[Spend] is a value for each transaction, at position 4"),
        ("SUM(SUM([Amount]))", "SUM() cannot contain another aggregate or a total, at position 5"),
        ("SUM([Amount] / spend)", "[Amount] is a value for each transaction, at position 5"),
        ("SUM(spend)", "SUM() cannot contain another aggregate or a total, at position 5"),
        ("SUM([Category])", "SUM() needs a number, not text, at position 5"),
        ("IF 1 THEN 2 END", "IF needs a true/false condition at position 4"),
        ("CASE WHEN 1 THEN 2 END", "CASE needs a true/false condition at position 11"),
        ("SUM(IF [Amount] > 1 THEN 'a' ELSE 2 END)", "This IF mixes text and a number"),
        ("SUM(IIF([Category] = 1, 1, 0))", "Cannot compare text with a number at position 20"),
        ("SUM(IIF([Date] > '2026-01-01', 1, 0))", 'Write a date as DATE("YYYY-MM-DD")'),
        ("IIF(TRUE < FALSE, 1, 0)", "Cannot order true/false values"),
        ("spend > 5", "must give a number, not true/false"),
        ("'Food'", "must give a number, not text"),
        ("DATE('2026-01-01')", "must give a number, not a date"),
        ("'a' + 1", "+ needs a number, not text, at position 1"),
        ("-'a'", "A minus sign needs a number, not text"),
        ("NOT 1", "NOT needs true/false, not a number, at position 5"),
        ("IIF(1 AND TRUE, 1, 0)", "AND needs true/false"),
        ("IF spend > 1 THEN 2", "Expected END for the IF at position 1"),
        ("IF spend > 1 2 END", "Expected THEN for the IF at position 1"),
        ("CASE spend WHEN 1 THEN 2", "Expected END for the CASE at position 1"),
        ("CASE spend ELSE 1 END", "The CASE at position 1 needs at least one WHEN"),
        ("1 < 2 < 3", "Comparisons cannot be chained, at position 7"),
        ("IIF(spend IN (1) IN (2), 1, 0)", "Comparisons cannot be chained"),
        ("SUM(IIF([Amount] IN ([Net]), 1, 0))", "must be a fixed value, at position 22"),
        ("SUM(IIF([Category] IN ('a', 1), 1, 0))", "IN (...) mixes text and a number"),
        ("SUM(IIF([Date] = DATE('2026-13-01'), 1, 0))", 'Not a date: "2026-13-01" at position 23'),
        ("DATE('1 March') + 0", 'Use DATE("YYYY-MM-DD")'),
        ("DATE(5)", "DATE() takes a date written as text"),
        ("ROUND(1, 9)", "ROUND() takes 0 to 6 decimal places, at position 10"),
        ("ROUND(1, 1.5)", "ROUND() takes 0 to 6 decimal places"),
        ("ROUND(spend, spend)", "The places of ROUND() must be a fixed value"),
        ("POWER(2, 101)", "POWER() takes a power from -100 to 100, at position 10"),
        ("MAX(DATEPART('hour', [Date]))", "DATEPART() takes 'year', 'quarter'"),
        ("MAX(DATEPART([Category], [Date]))", "The part of DATEPART() must be a fixed value"),
        ("'Food", "The text at position 1 has no closing '"),
        ('"Food', 'The text at position 1 has no closing "'),
        ("[Amount", "The field name at position 1 has no closing ]"),
        ("THEN", "Unexpected 'THEN' at position 1"),
        ("spend END", "Unexpected 'END' at position 7"),
        ("1 ! 2", "Unexpected character '!'"),
    ],
)
def test_a_bad_formula_is_refused_with_a_reason_and_a_position(text, complaint):
    with pytest.raises(FormulaError, match=re.escape(complaint)):
        compile_expression(text)


# --- missing values ------------------------------------------------------------------------------


def test_a_missing_value_spreads_through_arithmetic_and_comparisons():
    assert value("NULL") is None
    assert value("NULL + 1") is None
    assert value("AVG([Balance]) * 0") is None
    assert value("IIF(AVG([Balance]) > 0, 1, 2)") == D(2)  # a missing condition counts as false


def test_and_or_use_three_valued_logic():
    unknown = "AVG([Balance]) > 0"
    assert value(f"IIF({unknown} AND FALSE, 1, 2)") == D(2)
    assert value(f"IIF(ISNULL({unknown} AND TRUE), 1, 2)") == D(1)  # unknown AND true: unknown
    assert value(f"IIF({unknown} OR TRUE, 1, 2)") == D(1)
    assert value(f"IIF(ISNULL({unknown} OR FALSE), 1, 2)") == D(1)
    assert value(f"IIF(ISNULL(NOT {unknown}), 1, 2)") == D(1)


def test_an_if_without_else_is_missing_and_aggregations_skip_it():
    assert value("SUM(IF [Category] = 'Rent' THEN [Spend] END)") == D(0)  # SUM of nothing: 0
    assert value("COUNT(IF [Category] = 'Rent' THEN 1 END)") == D(0)
    assert value("AVG(IF [Category] = 'Rent' THEN [Spend] END)") is None  # AVG of nothing
    assert value("MIN(IF [Category] = 'Rent' THEN [Spend] END)") is None
    assert value("MEDIAN([Balance])") is None


def test_numbers_without_an_answer_are_missing():
    assert value("SQRT(-1)") is None
    assert value("spend / 0") is None
    assert value("spend % 0") is None
    assert value("POWER(0, -1)") is None
    assert value("POWER(2, spend)") is None  # a power past the limit, known only per group
    assert value("POWER(10, 100) * POWER(10, 100)") is None  # far past MAX_RESULT


def test_an_aggregation_of_the_spend_field_matches_the_totals():
    for field, total in (("Spend", "spend"), ("Income", "income"), ("Net", "net")):
        assert value(f"SUM([{field}])") == value(total)
    assert value("COUNT([Amount])") == value("count")


def test_the_fields_read_what_the_charts_read():
    rows = [*ROWS, row("5", balance=D("12.50"))]
    for each in rows:
        for measure in ("spend", "income", "net", "amount", "balance"):
            assert FIELDS[measure.title()][2](each) == engine.measure_value(each, measure)
        assert FIELDS["Category"][2](each) == engine.dimension_key(each, "category")
        assert FIELDS["Merchant"][2](each) == engine.dimension_key(each, "merchant")
        assert FIELDS["Type"][2](each) == engine.dimension_key(each, "txn_type")


# --- limits ----------------------------------------------------------------------------------------


def test_the_new_parts_count_towards_the_depth():
    ok = "IF TRUE THEN " * MAX_DEPTH + "1" + " END" * MAX_DEPTH
    assert value(ok) == D(1)
    with pytest.raises(FormulaError, match="nests"):
        compile_expression("IF TRUE THEN " * (MAX_DEPTH + 1) + "1" + " END" * (MAX_DEPTH + 1))
    with pytest.raises(FormulaError, match="nests"):
        compile_expression("IIF(" + "NOT " * (MAX_DEPTH + 1) + "TRUE, 1, 0)")


def test_an_in_list_and_a_text_have_a_limit():
    items = ", ".join(str(n) for n in range(MAX_IN_ITEMS + 1))
    with pytest.raises(FormulaError, match=f"at most {MAX_IN_ITEMS} values"):
        compile_expression(f"IIF(spend IN ({items}), 1, 0)")
    with pytest.raises(FormulaError, match=f"longer than {MAX_STRING} characters"):
        compile_expression(f"IIF(CONTAINS('{'a' * (MAX_STRING + 1)}', 'a'), 1, 0)")


def test_python_still_cannot_be_reached():
    for text in ("[Amount].__class__", "lambda: 1", "SUM([Amount]).real", "__import__('os')"):
        with pytest.raises(FormulaError):
            compile_expression(text)


def test_whitespace_is_tidied_except_inside_quotes():
    assert tidy("  SUM(IF  [Merchant] =\n'Big  Shop' THEN 1 END) ") == (
        "SUM(IF [Merchant] = 'Big  Shop' THEN 1 END)"
    )
    spec = validate_spec(
        {
            "chart": "kpi",
            "y": {
                "measure": "formula",
                "formula": {"expression": 'COUNTD(IF [Merchant] = "A  B" THEN 1 END)'},
            },
        }
    )
    assert '"A  B"' in spec["y"]["formula"]["expression"]


# --- days ------------------------------------------------------------------------------------------


def test_days_in_counts_calendar_days_and_can_keep_some_weekdays_or_months():
    assert days_in(*MARCH) == 31
    assert days_in(date(2026, 3, 5), date(2026, 3, 4)) == 0
    assert days_in(*MARCH, weekdays={0}) == 5  # the Mondays of March 2026
    assert days_in(date(2026, 1, 1), date(2026, 12, 31), months={2}) == 28
    assert days_in(date(2026, 1, 1), date(2026, 12, 31), weekdays={0}, months={3}) == 5


def test_a_group_covers_its_own_bucket_cut_to_the_range():
    dims = [("date", "month")]
    assert group_days(dims, (date(2026, 3, 1),), date(2026, 3, 15), date(2026, 4, 30)) == 17
    assert group_days(dims, (date(2026, 4, 1),), date(2026, 3, 15), date(2026, 4, 30)) == 30
    assert group_days([("weekday", None)], (5,), *MARCH) == 4  # the Saturdays
    assert group_days([("category", None)], ("Food",), *MARCH) == 31
    both = [("date", "week"), ("category", None)]
    assert group_days(both, (date(2026, 3, 30), "Food"), *MARCH) == 2  # Mon 30 and Tue 31


def test_days_is_only_worked_out_when_the_formula_uses_it():
    def never():
        raise AssertionError("days was worked out")

    assert value("spend / count", days=never) == D(25)
    assert value("spend / days", days=lambda: 4) == D(25)


def test_without_a_span_days_runs_from_the_first_transaction_to_the_last():
    assert value("days") == D(8)  # 2 to 9 March


def spec_for(expression, chart="bar", **extra):
    return validate_spec(
        {
            "chart": chart,
            "y": {"measure": "formula", "formula": {"expression": expression}},
            **extra,
        }
    )


def test_a_month_line_shows_average_daily_spend():
    rows = [
        {**row("31"), "date": date(2026, 3, 20)},  # March from the 15th: 17 days
        {**row("60"), "date": date(2026, 4, 2)},  # April: 30 days
    ]
    spec = spec_for("spend / days", "line", x={"field": "date", "granularity": "month"})
    result = run(spec, rows, (date(2026, 3, 15), date(2026, 4, 30)))
    assert [value for _, value in result["rows"]] == ["1.82", "2.00"]  # 31 / 17 and 60 / 30


def test_a_weekday_bar_divides_by_how_many_of_that_weekday_there_were():
    spec = spec_for("days", x={"field": "weekday"})
    by_day = dict(map(tuple, run(spec, ROWS, MARCH)["rows"]))
    shown = {label: days for label, days in by_day.items() if days is not None}
    assert sorted(shown.values()) == ["4.00", "5.00", "5.00"]  # Saturday 4, Monday 5, Sunday 5


def test_a_category_bar_and_a_kpi_cover_the_whole_period():
    bar = run(spec_for("days", x={"field": "category"}), ROWS, MARCH)
    assert {value for _, value in bar["rows"]} == {"31.00"}
    earlier = {**row("10"), "date": date(2026, 2, 10)}  # in 29 January to 28 February
    headline = run(spec_for("days", "kpi", kpi={"compare": "previous"}), [earlier, *ROWS], MARCH)
    assert headline["rows"][0][:2] == ["31.00", "31.00"]  # the previous period is as long


# --- through the service ---------------------------------------------------------------------------


@pytest.fixture
def carol(db):
    user = make_user("carol@example.com")
    for day, amount, kind, category, name in (
        (2, "30", "debit", "Food", "Moonbeam Market"),
        (7, "20", "debit", "Food", "Corner Grocer"),
        (9, "200", "credit", "Salary", "Zentro Works"),
    ):
        make_txn(
            user,
            date=date(2026, 3, day),
            amount=D(amount),
            txn_type=kind,
            name=name,
            description="d",
            balance=D("100.00"),
            category=Category.objects.get(user=user, name=category),
        )
    return user


FILTERS = {"date": {"preset": "custom", "from": "2026-03-01", "to": "2026-03-31"}}


def kpi(expression):
    return {"chart": "kpi", "y": {"measure": "formula", "formula": {"expression": expression}}}


def test_a_formula_says_which_encrypted_fields_it_reads():
    assert fields_used("spend") == frozenset()
    assert fields_used("COUNTD([Merchant])") == {"name"}
    assert fields_used("AVG([Balance]) + SUM(IIF(CONTAINS([Merchant], 'a'), 1, 0))") == {
        "name",
        "balance",
    }


def test_the_batch_decrypts_merchants_and_balances_for_a_formula(carol):
    results = services.run_queries(
        carol,
        FILTERS,
        [
            {"key": "merchants", "spec": kpi("COUNTD([Merchant])")},
            {"key": "balance", "spec": kpi("AVG([Balance])")},
            {"key": "grocer", "spec": kpi("SUM(IIF(CONTAINS([Merchant], 'grocer'), [Spend], 0))")},
        ],
        today=date(2026, 4, 1),
    )
    assert results["merchants"]["rows"][0][0] == "3.00"
    assert results["balance"]["rows"][0][0] == "100.00"
    assert results["grocer"]["rows"][0][0] == "20.00"


def test_the_rows_behind_a_weekday_bar_use_that_weekdays_days(carol):
    bar = {**kpi("days"), "chart": "bar", "x": {"field": "weekday"}}
    body = services.list_rows(carol, FILTERS, bar, {"weekdays": [0]}, today=date(2026, 4, 1))
    assert body["total"] == 2  # 2 and 9 March, both Mondays
    assert body["value"] == "5.00"  # five Mondays in March 2026


def test_the_rows_behind_a_formula_with_merchants_read_the_names(carol):
    body = services.list_rows(carol, FILTERS, kpi("COUNTD([Merchant])"), today=date(2026, 4, 1))
    assert body["value"] == "3.00"


# --- what is stored, and who can read it ------------------------------------------------------------

SECRET = "Quillfeather Traders"  # text a user might put in a formula


def test_the_text_in_a_formula_is_never_stored_readably(carol):
    from django.db import connection

    from insights.models import Dashboard, Panel
    from vault.services import UserCipher

    cipher = UserCipher(carol)
    spec = kpi(f'SUM(IF [Merchant] = "{SECRET}" THEN [Spend] END)')
    dashboard = Dashboard.objects.create(
        user=carol, name_enc=services.encrypt_text(cipher, "Review", services.DASHBOARD_NAME)
    )
    panel = Panel.objects.create(
        dashboard=dashboard,
        title_enc=services.encrypt_text(cipher, "Share", services.PANEL_TITLE),
        config_enc=services.encrypt_config(cipher, spec),
        x=0,
        y=0,
        w=6,
        h=4,
    )
    with connection.cursor() as cursor:
        cursor.execute("SELECT * FROM insights_panel WHERE id = %s", [panel.id])
        stored = cursor.fetchone()
    for column in stored:
        raw = bytes(column) if isinstance(column, memoryview | bytes) else str(column).encode()
        assert SECRET.encode() not in raw
        assert b"Merchant" not in raw

    # Only this account's key opens it, and it comes back exactly as written.
    saved = services.decrypt_config(cipher, Panel.objects.get(pk=panel.pk).config_enc)
    assert SECRET in saved["y"]["formula"]["expression"]
    with pytest.raises(Exception):  # noqa: B017 - any failure to decrypt is the point
        services.decrypt_config(UserCipher(make_user("dave@example.com")), panel.config_enc)


def test_a_formula_only_ever_sees_its_own_accounts_transactions(carol):
    other = make_user("erin@example.com")
    make_txn(
        other,
        date=date(2026, 3, 5),
        amount=D("999"),
        txn_type="debit",
        name="Elsewhere Store",
        description="d",
        category=Category.objects.get(user=other, name="Food"),
    )
    results = services.run_queries(
        carol,
        FILTERS,
        [
            {"key": "spend", "spec": kpi("SUM([Spend])")},
            {"key": "merchants", "spec": kpi("COUNTD([Merchant])")},
        ],
        today=date(2026, 4, 1),
    )
    assert results["spend"]["rows"][0][0] == "50.00"  # carol's 30 + 20, not erin's 999
    assert results["merchants"]["rows"][0][0] == "3.00"


def test_an_error_message_only_repeats_the_formula_it_was_given():
    secret_formula = f"SUM(IF [Merchant] = '{SECRET}' THEN [Spend] END) + [Amount]"
    with pytest.raises(FormulaError) as caught:
        compile_expression(secret_formula)
    assert "Quillfeather" not in str(caught.value)  # field and position, not the quoted text

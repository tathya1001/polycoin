from datetime import date
from decimal import Decimal

import pytest

from categories.models import Category
from categories.services import get_default_category
from insights import services
from insights.spec import SpecError
from transactions.tests import make_txn, make_user

pytestmark = pytest.mark.django_db

START, END = date(2026, 1, 1), date(2026, 1, 31)


@pytest.fixture
def alice():
    return make_user("alice@example.com")


@pytest.fixture
def bob():
    return make_user("bob@example.com")


def test_rows_have_the_keys_the_engine_reads(alice):
    make_txn(alice, amount=Decimal("12.50"), name="Tastybites")
    [row] = services.load_rows(alice, START, END, need=frozenset({"name", "balance"}))
    assert row["date"] == date(2026, 1, 5)
    assert row["txn_type"] == "debit"
    assert row["category_name"] == get_default_category(alice).name
    assert row["amount"] == Decimal("12.50")
    assert row["name"] == "Tastybites"
    assert row["balance"] == Decimal("100.00")


def test_name_and_balance_are_skipped_unless_needed(alice):
    make_txn(alice)
    [row] = services.load_rows(alice, START, END)
    assert row["name"] == ""
    assert row["balance"] is None


def test_a_missing_balance_stays_none_even_when_needed(alice):
    make_txn(alice, balance=None)
    [row] = services.load_rows(alice, START, END, need=frozenset({"balance"}))
    assert row["balance"] is None


def test_date_range_is_inclusive_at_both_ends(alice):
    make_txn(alice, date=date(2025, 12, 31), amount=Decimal("1.00"))
    make_txn(alice, date=START, amount=Decimal("2.00"))
    make_txn(alice, date=END, amount=Decimal("3.00"))
    make_txn(alice, date=date(2026, 2, 1), amount=Decimal("4.00"))
    rows = services.load_rows(alice, START, END)
    assert sorted(row["amount"] for row in rows) == [Decimal("2.00"), Decimal("3.00")]


def test_type_filter(alice):
    make_txn(alice, txn_type="debit", amount=Decimal("1.00"))
    make_txn(alice, txn_type="credit", amount=Decimal("2.00"))
    rows = services.load_rows(alice, START, END, types=("credit",))
    assert [row["amount"] for row in rows] == [Decimal("2.00")]


def test_category_filter(alice):
    other = Category.objects.filter(user=alice, is_default=False).first()
    make_txn(alice, amount=Decimal("1.00"))  # lands in the default category
    make_txn(alice, amount=Decimal("2.00"), category=other)
    rows = services.load_rows(alice, START, END, category_ids=(other.id,))
    assert [row["amount"] for row in rows] == [Decimal("2.00")]
    assert rows[0]["category_id"] == str(other.id)


def test_never_returns_another_users_rows(alice, bob):
    make_txn(alice, amount=Decimal("1.00"))
    make_txn(bob, amount=Decimal("2.00"))
    assert [row["amount"] for row in services.load_rows(alice, START, END)] == [Decimal("1.00")]


def test_row_cap_raises_before_decrypting(alice, settings):
    settings.INSIGHTS_MAX_ROWS = 2
    for cents in (1, 2, 3):
        make_txn(alice, amount=Decimal(cents))
    with pytest.raises(services.TooManyRows):
        services.load_rows(alice, START, END)


def test_row_cap_allows_exactly_the_limit(alice, settings):
    settings.INSIGHTS_MAX_ROWS = 2
    for cents in (1, 2):
        make_txn(alice, amount=Decimal(cents))
    assert len(services.load_rows(alice, START, END)) == 2


# --- first_transaction_date ---------------------------------------------------


def test_first_transaction_date_is_none_without_transactions(alice):
    assert services.first_transaction_date(alice) is None


def test_first_transaction_date_is_the_oldest(alice):
    make_txn(alice, date=date(2026, 3, 1), amount=Decimal("1.00"))
    make_txn(alice, date=date(2025, 11, 9), amount=Decimal("2.00"))
    assert services.first_transaction_date(alice) == date(2025, 11, 9)


# --- run_queries --------------------------------------------------------------

TODAY = date(2026, 5, 15)


def panel(chart="kpi", measure="spend", **extra):
    """A minimal raw spec. `extra` adds keys such as x, color, filters, kpi."""
    return {"chart": chart, "y": {"measure": measure}, **extra}


def run(user, queries, global_filters=None):
    return services.run_queries(user, global_filters or {}, queries, today=TODAY)


def test_no_queries_gives_no_results(alice):
    assert run(alice, []) == {}


def test_all_preset_starts_at_the_first_transaction(alice):
    make_txn(alice, date=date(2026, 3, 10), amount=Decimal("5.00"))
    spec = panel(
        "line",
        x={"field": "date", "granularity": "month"},
        filters={"date": {"preset": "all"}},
    )
    result = run(alice, [{"key": "p", "spec": spec}])["p"]
    assert [row[0] for row in result["rows"]] == ["2026-03-01", "2026-04-01", "2026-05-01"]


def test_all_preset_without_transactions_is_a_single_bucket(alice):
    spec = panel(
        "line",
        x={"field": "date", "granularity": "month"},
        filters={"date": {"preset": "all"}},
    )
    result = run(alice, [{"key": "p", "spec": spec}])["p"]
    assert [row[0] for row in result["rows"]] == ["2026-05-01"]


def test_each_result_carries_the_period_it_covers(alice):
    spec = panel(filters={"date": {"preset": "this_month"}})
    result = run(alice, [{"key": "k", "spec": spec}])["k"]
    assert result["period"] == {"from": "2026-05-01", "to": "2026-05-15"}


def test_the_all_period_starts_at_the_first_transaction(alice):
    make_txn(alice, date=date(2026, 3, 10), amount=Decimal("5.00"))
    result = run(alice, [{"key": "k", "spec": panel(filters={"date": {"preset": "all"}})}])["k"]
    assert result["period"] == {"from": "2026-03-10", "to": "2026-05-15"}


def test_a_bad_panel_does_not_break_the_good_one(alice):
    make_txn(alice, date=date(2026, 5, 5), amount=Decimal("7.00"))
    results = run(
        alice,
        [{"key": "bad", "spec": {"chart": "nope"}}, {"key": "good", "spec": panel()}],
    )
    assert results["bad"]["error"]["code"] == "invalid_spec"
    assert results["good"]["rows"] == [["7.00", None, None]]


def test_too_many_buckets_is_an_error_for_that_panel_only(alice):
    make_txn(alice, date=date(2026, 5, 5), amount=Decimal("7.00"))
    huge = panel(
        "line",
        x={"field": "date", "granularity": "day"},
        filters={"date": {"preset": "custom", "from": "2020-01-01", "to": "2026-01-01"}},
    )
    results = run(alice, [{"key": "huge", "spec": huge}, {"key": "ok", "spec": panel()}])
    assert results["huge"]["error"]["code"] == "too_many_points"
    assert results["ok"]["rows"][0][0] == "7.00"


def test_row_cap_is_an_error_for_every_panel(alice, settings):
    settings.INSIGHTS_MAX_ROWS = 1
    make_txn(alice, date=date(2026, 5, 5), amount=Decimal("1.00"))
    make_txn(alice, date=date(2026, 5, 6), amount=Decimal("2.00"))
    results = run(alice, [{"key": "a", "spec": panel()}, {"key": "b", "spec": panel()}])
    assert results["a"]["error"]["code"] == "too_many_rows"
    assert results["b"]["error"]["code"] == "too_many_rows"


def test_kpi_compare_uses_the_previous_period(alice):
    # "this_month" on 2026-05-15 is May 1-15, so the previous period is April 16-30.
    make_txn(alice, date=date(2026, 5, 5), amount=Decimal("100.00"))
    make_txn(alice, date=date(2026, 4, 20), amount=Decimal("50.00"))
    spec = panel(kpi={"compare": "previous"}, filters={"date": {"preset": "this_month"}})
    result = run(alice, [{"key": "k", "spec": spec}])["k"]
    assert result["rows"] == [["100.00", "50.00", "100.0"]]


def test_a_panels_own_type_beats_the_dashboard_filter(alice):
    make_txn(alice, date=date(2026, 5, 5), txn_type="credit", amount=Decimal("20.00"))
    make_txn(alice, date=date(2026, 5, 6), txn_type="debit", amount=Decimal("7.00"))
    inherits = panel(measure="amount")
    pinned = panel(measure="amount", filters={"type": "debit"})
    results = run(
        alice,
        [{"key": "inherits", "spec": inherits}, {"key": "pinned", "spec": pinned}],
        global_filters={"type": "credit"},
    )
    assert results["inherits"]["rows"][0][0] == "20.00"
    assert results["pinned"]["rows"][0][0] == "7.00"


def test_category_filter_in_a_query(alice):
    other = Category.objects.filter(user=alice, is_default=False).first()
    make_txn(alice, date=date(2026, 5, 5), amount=Decimal("1.00"))
    make_txn(alice, date=date(2026, 5, 6), amount=Decimal("2.00"), category=other)
    spec = panel(measure="count", filters={"categories": [str(other.id)]})
    assert run(alice, [{"key": "k", "spec": spec}])["k"]["rows"][0][0] == "1"


def test_merchant_contains_ignores_case(alice):
    make_txn(alice, date=date(2026, 5, 5), amount=Decimal("1.00"), name="Tastybites Cafe")
    make_txn(alice, date=date(2026, 5, 6), amount=Decimal("2.00"), name="Fuelstop")
    spec = panel(measure="count", filters={"merchant_contains": "TASTY"})
    assert run(alice, [{"key": "k", "spec": spec}])["k"]["rows"][0][0] == "1"


def test_balance_measure_reads_the_last_balance_in_each_bucket(alice):
    make_txn(alice, date=date(2026, 1, 5), amount=Decimal("1.00"), balance=Decimal("100.00"))
    make_txn(alice, date=date(2026, 1, 20), amount=Decimal("2.00"), balance=Decimal("80.00"))
    spec = panel(
        "line",
        measure="balance",
        x={"field": "date", "granularity": "month"},
        filters={"date": {"preset": "this_year"}},
    )
    result = run(alice, [{"key": "p", "spec": spec}])["p"]
    assert result["rows"][0] == ["2026-01-01", "80.00"]


def test_merchant_dimension_merges_spellings(alice):
    make_txn(alice, date=date(2026, 5, 5), amount=Decimal("10.00"), name="TASTYBITES")
    make_txn(alice, date=date(2026, 5, 6), amount=Decimal("20.00"), name="tastybites ")
    spec = panel("bar", x={"field": "merchant"})
    result = run(alice, [{"key": "p", "spec": spec}])["p"]
    assert result["rows"] == [["Tastybites", "30.00"]]


def test_run_queries_never_includes_another_users_transactions(alice, bob):
    make_txn(alice, date=date(2026, 5, 5), amount=Decimal("1.00"))
    make_txn(bob, date=date(2026, 5, 5), amount=Decimal("99.00"))
    assert run(alice, [{"key": "k", "spec": panel()}])["k"]["rows"][0][0] == "1.00"


def test_invalid_dashboard_filters_raise(alice):
    with pytest.raises(SpecError):
        run(alice, [], global_filters={"type": "nope"})


# --- a panel's own categories and the dashboard's ---------------------------------
# A panel with categories of its own uses only those; one without follows the dashboard bar.


def category_ids(user, *names):
    return [str(Category.objects.get(user=user, name=name).id) for name in names]


@pytest.fixture
def month(alice):
    """Food 40, Groceries 25, Health 15 and Rent 300 out, Salary 100 in, all this month."""
    for day, name, kind, amount in (
        (5, "Food", "debit", "40.00"),
        (6, "Groceries", "debit", "25.00"),
        (7, "Health", "debit", "15.00"),
        (8, "Salary", "credit", "100.00"),
        (9, "Rent", "debit", "300.00"),
    ):
        make_txn(
            alice,
            date=date(2026, 5, day),
            txn_type=kind,
            amount=Decimal(amount),
            category=Category.objects.get(user=alice, name=name),
        )
    return alice


def value(results, key):
    return results[key]["rows"][0][0]


def test_a_panels_own_categories_beat_the_dashboards(month):
    spec = panel(filters={"categories": category_ids(month, "Food", "Groceries")})
    results = run(
        month,
        [{"key": "k", "spec": spec}],
        global_filters={"categories": category_ids(month, "Rent")},
    )
    assert value(results, "k") == "65.00"


def test_a_panels_own_categories_beat_a_dashboard_that_picks_every_category(month):
    every = [str(category.id) for category in Category.objects.filter(user=month)]
    spec = panel(filters={"categories": category_ids(month, "Food", "Groceries")})
    results = run(month, [{"key": "k", "spec": spec}], global_filters={"categories": every})
    assert value(results, "k") == "65.00"


def test_a_panel_without_categories_follows_the_dashboards(month):
    results = run(
        month,
        [{"key": "k", "spec": panel()}],
        global_filters={"categories": category_ids(month, "Rent", "Health")},
    )
    assert value(results, "k") == "315.00"


def test_without_categories_on_either_a_panel_sees_every_category(month):
    assert value(run(month, [{"key": "k", "spec": panel()}]), "k") == "380.00"


@pytest.mark.parametrize(
    ("measure", "expected"),
    [("spend", "65.00"), ("income", "100.00"), ("net", "35.00"), ("count", "3")],
)
def test_a_panels_own_categories_win_for_every_measure(month, measure, expected):
    spec = panel(
        measure=measure,
        filters={"categories": category_ids(month, "Food", "Groceries", "Salary")},
    )
    results = run(
        month,
        [{"key": "k", "spec": spec}],
        global_filters={"categories": category_ids(month, "Rent")},
    )
    assert value(results, "k") == expected


def test_a_panels_own_categories_win_for_a_calculated_field(month):
    spec = {
        "chart": "kpi",
        "y": {"measure": "formula", "formula": {"expression": "income - spend"}},
        "filters": {"categories": category_ids(month, "Food", "Groceries", "Salary")},
    }
    results = run(
        month,
        [{"key": "k", "spec": spec}],
        global_filters={"categories": category_ids(month, "Rent")},
    )
    assert Decimal(value(results, "k")) == Decimal("35")


def test_one_batch_serves_panels_with_and_without_their_own_categories(month):
    # The batch loads its rows once, narrowed to what the panels ask for between them: each
    # panel must still get every row it needs, and no row it does not.
    queries = [
        {"key": "food", "spec": panel(filters={"categories": category_ids(month, "Food")})},
        {"key": "health", "spec": panel(filters={"categories": category_ids(month, "Health")})},
        {"key": "inherits", "spec": panel()},
    ]
    results = run(month, queries, global_filters={"categories": category_ids(month, "Rent")})
    assert value(results, "food") == "40.00"
    assert value(results, "health") == "15.00"
    assert value(results, "inherits") == "300.00"


def test_the_dashboards_type_still_applies_to_a_panel_with_its_own_categories(month):
    # Each filter falls back on its own: own categories do not drop the dashboard's type.
    spec = panel(measure="count", filters={"categories": category_ids(month, "Food", "Salary")})
    results = run(month, [{"key": "k", "spec": spec}], global_filters={"type": "credit"})
    assert value(results, "k") == "1"


def test_a_click_on_another_panel_narrows_within_the_panels_own_categories(month):
    own = panel(filters={"categories": category_ids(month, "Food", "Groceries")})
    queries = [
        {"key": "k", "spec": own},
        {"key": "source", "spec": panel("bar", x={"field": "category"})},
    ]
    every = [str(category.id) for category in Category.objects.filter(user=month)]

    def clicked(name):
        return services.run_queries(
            month,
            {"categories": every},
            queries,
            today=TODAY,
            selection={"categories": [name]},
            selection_source="source",
        )

    assert value(clicked("Groceries"), "k") == "25.00"
    assert value(clicked("Rent"), "k") == "0.00"  # outside the panel's categories


def test_a_kpi_compares_with_the_panels_own_categories_too(month):
    # "this_month" on 2026-05-15 is May 1-15, so the previous period is April 16-30.
    for name, amount in (("Food", "10.00"), ("Rent", "500.00")):
        make_txn(
            month,
            date=date(2026, 4, 20),
            amount=Decimal(amount),
            category=Category.objects.get(user=month, name=name),
        )
    spec = panel(
        kpi={"compare": "previous"},
        filters={
            "date": {"preset": "this_month"},
            "categories": category_ids(month, "Food", "Groceries"),
        },
    )
    results = run(
        month,
        [{"key": "k", "spec": spec}],
        global_filters={"categories": category_ids(month, "Rent")},
    )
    assert results["k"]["rows"][0][:2] == ["65.00", "10.00"]


def test_the_rows_behind_a_panel_follow_its_own_categories(month):
    spec = panel(filters={"categories": category_ids(month, "Food", "Groceries")})
    body = services.list_rows(
        month, {"categories": category_ids(month, "Rent")}, spec, None, today=TODAY
    )
    assert sorted(row["category"] for row in body["rows"]) == ["Food", "Groceries"]


def test_the_rows_behind_a_panel_without_categories_follow_the_dashboards(month):
    body = services.list_rows(
        month, {"categories": category_ids(month, "Rent")}, panel(), None, today=TODAY
    )
    assert [row["category"] for row in body["rows"]] == ["Rent"]

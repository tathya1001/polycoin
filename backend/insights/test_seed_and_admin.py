"""The dev-only demo-data command and the admin pages for dashboards and panels."""

import random
from datetime import date
from decimal import Decimal

import pytest
from django.core.management import CommandError, call_command
from django.test import Client
from django.utils import timezone

from accounts.models import User
from categories.models import Category
from insights import services
from insights.engine import add_months
from insights.management.commands.seed_demo_transactions import (
    EVERYDAY,
    MONTHLY,
    OPENING_BALANCE,
    build_rows,
)
from insights.templates import TEMPLATES
from insights.test_models import CONFIG, NAME, TITLE, make_dashboard, make_panel
from transactions.models import Transaction
from transactions.tests import make_txn, make_user
from vault.services import UserCipher

pytestmark = pytest.mark.django_db

MERCHANTS = {merchant for _, _, _, merchant, _, _ in MONTHLY} | {
    merchant for _, merchants, _, _, _ in EVERYDAY for merchant in merchants
}
EVERYDAY_PER_MONTH = sum(per_month for *_, per_month in EVERYDAY)


@pytest.fixture
def alice():
    return make_user("alice@example.com")


@pytest.fixture
def debug(settings):
    settings.DEBUG = True


def seed(user, **options):
    call_command("seed_demo_transactions", user=user.email, **options)


def decrypted(user, field, context):
    cipher = UserCipher(user)
    return [
        cipher.decrypt(bytes(getattr(txn, field)), context).decode()
        for txn in Transaction.objects.filter(user=user)
    ]


# --- build_rows (pure) --------------------------------------------------------


def test_rows_cover_the_months_and_stop_today():
    today = date(2026, 5, 20)  # after every MONTHLY day, so each month has all of them
    rows = build_rows(today, 3, 1, random.Random(1))

    assert len(rows) == 3 * (len(MONTHLY) + EVERYDAY_PER_MONTH)
    assert rows[0]["date"] >= date(2026, 3, 1)
    assert rows[-1]["date"] <= today
    assert [row["date"] for row in rows] == sorted(row["date"] for row in rows)


def test_scale_multiplies_only_the_everyday_spends():
    today = date(2026, 5, 20)
    rows = build_rows(today, 3, 2, random.Random(1))
    assert len(rows) == 3 * (len(MONTHLY) + 2 * EVERYDAY_PER_MONTH)


def test_nothing_is_dated_after_today_in_the_current_month():
    today = date(2026, 5, 2)  # before rent day (the 3rd)
    rows = build_rows(today, 1, 1, random.Random(1))
    assert all(row["date"] <= today for row in rows)
    assert "Maple Street Homes" not in {row["name"] for row in rows}


def test_the_same_seed_gives_the_same_rows():
    today = date(2026, 5, 20)
    assert build_rows(today, 2, 1, random.Random(7)) == build_rows(today, 2, 1, random.Random(7))


def test_balances_run_from_the_opening_balance():
    rows = build_rows(date(2026, 5, 20), 2, 1, random.Random(3))
    credits = sum(row["amount"] for row in rows if row["txn_type"] == "credit")
    debits = sum(row["amount"] for row in rows if row["txn_type"] == "debit")
    assert rows[-1]["balance"] == OPENING_BALANCE + credits - debits


def test_amounts_are_positive_whole_paise():
    for row in build_rows(date(2026, 5, 20), 2, 1, random.Random(5)):
        assert row["amount"] > 0
        assert row["amount"] == row["amount"].quantize(Decimal("0.01"))


def test_descriptions_are_unique_so_fingerprints_never_collide():
    rows = build_rows(date(2026, 5, 20), 3, 2, random.Random(1))
    assert len({row["description"] for row in rows}) == len(rows)


# --- the command: guards ------------------------------------------------------


def test_refuses_to_run_without_debug(alice, settings):
    settings.DEBUG = False
    with pytest.raises(CommandError, match="DEBUG"):
        seed(alice)
    assert Transaction.objects.count() == 0


def test_refuses_an_unknown_user(debug):
    with pytest.raises(CommandError, match="No user"):
        call_command("seed_demo_transactions", user="nobody@example.com")


def test_refuses_a_user_who_already_has_transactions(alice, debug):
    make_txn(alice)
    with pytest.raises(CommandError, match="already has transactions"):
        seed(alice)
    assert Transaction.objects.count() == 1


@pytest.mark.parametrize("options", [{"months": 0}, {"months": 61}, {"scale": 0}, {"scale": 101}])
def test_refuses_out_of_range_options(alice, debug, options):
    with pytest.raises(CommandError):
        seed(alice, **options)
    assert Transaction.objects.count() == 0


# --- the command: what it writes ----------------------------------------------


def test_seeds_the_rows_build_rows_describes(alice, debug):
    seed(alice, months=3, seed=7)
    expected = build_rows(timezone.localdate(), 3, 1, random.Random(7))
    assert Transaction.objects.filter(user=alice).count() == len(expected)


def test_one_salary_credit_per_month_in_the_salary_category(alice, debug):
    seed(alice, months=4, seed=1)
    salaries = Transaction.objects.filter(user=alice, txn_type="credit")
    assert salaries.count() == 4
    assert {txn.category.name for txn in salaries} == {"Salary"}


def test_dates_stay_inside_the_requested_months(alice, debug):
    seed(alice, months=3, seed=2)
    today = timezone.localdate()
    dates = Transaction.objects.filter(user=alice).values_list("date", flat=True)
    assert min(dates) >= add_months(today.replace(day=1), -2)
    assert max(dates) <= today


def test_only_fictional_merchant_names_are_written(alice, debug):
    seed(alice, months=2, seed=3)
    assert set(decrypted(alice, "name_enc", "txn.name")) <= MERCHANTS


def test_rows_land_in_their_seed_categories(alice, debug):
    seed(alice, months=2, seed=4)
    used = set(Transaction.objects.filter(user=alice).values_list("category__name", flat=True))
    assert {"Food", "Groceries", "Rent", "Salary"} <= used
    assert "Others" not in used


def test_a_missing_category_falls_back_to_the_default(alice, debug):
    Category.objects.filter(user=alice, name="Health").delete()  # no transactions use it yet
    seed(alice, months=2, seed=5)
    assert Transaction.objects.filter(user=alice, category__name="Others").exists()


def test_the_final_balance_matches_the_row_totals(alice, debug):
    seed(alice, months=2, seed=6)
    cipher = UserCipher(alice)
    net, balances = Decimal(0), set()
    for txn in Transaction.objects.filter(user=alice):  # one pass: amount and type stay paired
        amount = Decimal(cipher.decrypt(bytes(txn.amount_enc), "txn.amount").decode())
        net += amount if txn.txn_type == "credit" else -amount
        balances.add(Decimal(cipher.decrypt(bytes(txn.balance_enc), "txn.balance").decode()))
    assert OPENING_BALANCE + net in balances  # the newest row holds the closing balance


def test_the_overview_template_runs_on_seeded_data(alice, debug):
    seed(alice, months=12, seed=8)
    queries = [
        {"key": str(index), "spec": panel["config"]}
        for index, panel in enumerate(TEMPLATES["overview"])
    ]
    for result in services.run_queries(alice, {}, queries).values():
        assert "error" not in result
        assert result["rows"]


# --- admin --------------------------------------------------------------------


@pytest.fixture
def admin_client():
    admin = User.objects.create_superuser(email="admin@example.com", password="x-Str0ng-pass!")
    client = Client()
    client.force_login(admin)
    return client


def test_admin_lists_show_no_plaintext(alice, admin_client):
    secret_config = {**CONFIG, "filters": {"merchant_contains": "tastybites"}}
    make_panel(make_dashboard(alice), config=secret_config)

    for url in ("/admin/insights/dashboard/", "/admin/insights/panel/"):
        response = admin_client.get(url)
        assert response.status_code == 200
        page = response.content.decode()
        assert NAME not in page
        assert TITLE not in page
        assert "tastybites" not in page


def test_admin_detail_pages_show_no_plaintext(alice, admin_client):
    dashboard = make_dashboard(alice)
    panel = make_panel(dashboard)

    for url in (
        f"/admin/insights/dashboard/{dashboard.id}/change/",
        f"/admin/insights/panel/{panel.id}/change/",
    ):
        response = admin_client.get(url)
        assert response.status_code == 200
        assert NAME not in response.content.decode()
        assert TITLE not in response.content.decode()


def test_admin_cannot_add_dashboards_or_panels(admin_client):
    assert admin_client.get("/admin/insights/dashboard/add/").status_code == 403
    assert admin_client.get("/admin/insights/panel/add/").status_code == 403

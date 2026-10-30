"""The Data Sources API: names, order, deleting, and what a rename does to formulas."""

import json
from datetime import date
from decimal import Decimal

import pytest
from django.db import connection
from rest_framework.test import APIClient

from datasources.models import MAX_SOURCE_NAME, MAX_SOURCES_PER_USER, DataSource
from datasources.services import first_source, sources_for
from insights.models import Dashboard, Panel
from insights.services import (
    DASHBOARD_NAME,
    PANEL_CONFIG,
    PANEL_TITLE,
    encrypt_config,
    encrypt_text,
)
from transactions.models import Transaction, TransferLink
from transactions.tests import make_txn, make_user
from vault.services import UserCipher

pytestmark = pytest.mark.django_db

URL = "/api/data-sources/"


@pytest.fixture
def alice():
    return make_user("alice@example.com")


@pytest.fixture
def api(alice):
    client = APIClient()
    client.force_authenticate(alice)
    return client


def add(api, name, **extra):
    return api.post(URL, {"name": name, **extra}, format="json")


def panel_with(user, config):
    cipher = UserCipher(user)
    dashboard = Dashboard.objects.create(
        user=user, name_enc=encrypt_text(cipher, "Home", DASHBOARD_NAME)
    )
    return Panel.objects.create(
        dashboard=dashboard,
        title_enc=encrypt_text(cipher, "One", PANEL_TITLE),
        config_enc=encrypt_config(cipher, config),
        x=0,
        y=0,
        w=6,
        h=4,
    )


def stored_formula(user, panel) -> str:
    panel.refresh_from_db()
    blob = UserCipher(user).decrypt(bytes(panel.config_enc), PANEL_CONFIG)
    return json.loads(blob)["y"]["formula"]["expression"]


def formula(text):
    return {
        "chart": "kpi",
        "y": {"measure": "formula", "formula": {"expression": text, "as": "money"}},
    }


def test_the_first_source_is_named_on_first_use_and_stays_that_way(alice, api):
    assert first_source(alice).name_enc is None
    [listed] = api.get(URL).data
    assert listed["name"] == "Main"
    stored = DataSource.objects.get(user=alice)
    assert stored.name_enc is not None and stored.name_index is not None
    assert api.get(URL).data[0]["id"] == listed["id"]


def test_a_new_source_gets_a_free_colour_and_the_next_place(api):
    api.get(URL)
    body = add(api, "Oak Salary").data
    assert body["name"] == "Oak Salary"
    assert body["position"] == 1
    assert body["color"] != api.get(URL).data[0]["color"]


def test_the_list_says_what_a_source_holds(alice, api):
    source = first_source(alice)
    make_txn(alice, data_source=source, date=date(2026, 1, 5), balance=Decimal("90.00"))
    make_txn(
        alice,
        data_source=source,
        date=date(2026, 3, 5),
        balance=Decimal("70.00"),
        description="later",
    )
    [listed] = api.get(URL).data
    assert listed["transactions"] == 2
    assert (listed["first_date"], listed["last_date"]) == ("2026-01-05", "2026-03-05")
    assert listed["balance"] == "70.00"


def test_the_name_is_never_stored_in_the_clear(alice, api):
    add(api, "Oak Salary")
    with connection.cursor() as cursor:
        cursor.execute("SELECT * FROM datasources_datasource")
        rows = cursor.fetchall()
    for row in rows:
        for value in row:
            raw = bytes(value) if isinstance(value, (bytes, memoryview)) else str(value).encode()
            assert b"Oak Salary" not in raw


@pytest.mark.parametrize(
    "name",
    ["", "   ", "Oak.Bank", "[Oak]", "Oak]", "x" * (MAX_SOURCE_NAME + 1)],
)
def test_a_name_that_would_break_formulas_is_refused(api, name):
    response = add(api, name)
    assert response.status_code == 400
    assert response.data["code"] == "invalid_name"


def test_spaces_are_tidied(api):
    assert add(api, "  Oak    Salary ").data["name"] == "Oak Salary"


def test_two_sources_cant_share_a_name_whatever_the_case(api):
    add(api, "Oak Salary")
    response = add(api, "oak  SALARY")
    assert response.status_code == 409
    assert response.data["code"] == "name_taken"


def test_the_starter_name_counts_too(api):
    assert add(api, "main").status_code == 409


def test_there_is_a_limit(alice, api):
    for number in range(MAX_SOURCES_PER_USER - 1):
        assert add(api, f"Source {number}").status_code == 201
    assert add(api, "One too many").data["code"] == "too_many"


def test_a_bad_colour_is_refused_and_a_good_one_kept(api):
    assert add(api, "A", color="red").status_code == 400
    assert add(api, "A", color="#ff8800").data["color"] == "#FF8800"


def test_a_source_can_be_recoloured(api):
    pk = add(api, "A").data["id"]
    assert api.patch(f"{URL}{pk}/", {"color": "#123ABC"}, format="json").data["color"] == "#123ABC"


def test_another_users_source_is_404(alice, api):
    bob = make_user("bob@example.com")
    source = first_source(bob)
    assert api.patch(f"{URL}{source.pk}/", {"name": "x"}, format="json").status_code == 404
    assert api.post(f"{URL}{source.pk}/remove/", {}, format="json").status_code == 404
    assert api.get(f"{URL}{source.pk}/usage/").status_code == 404


def test_you_only_see_your_own(api):
    bob = make_user("bob@example.com")
    first_source(bob)
    assert len(api.get(URL).data) == 1


def test_renaming_rewrites_the_formulas_that_name_it(alice, api):
    pk = add(api, "OakBank").data["id"]
    panel = panel_with(alice, formula("OakBank.spend - Main.income + [Other One].net"))
    unrelated = panel_with(alice, formula("Main.spend"))

    response = api.patch(f"{URL}{pk}/", {"name": "Oak Salary"}, format="json")

    assert response.data["name"] == "Oak Salary"
    assert stored_formula(alice, panel) == "[Oak Salary].spend - Main.income + [Other One].net"
    assert stored_formula(alice, unrelated) == "Main.spend"


def test_a_rename_to_a_taken_name_changes_nothing(alice, api):
    pk = add(api, "OakBank").data["id"]
    add(api, "River")
    panel = panel_with(alice, formula("OakBank.spend"))

    assert api.patch(f"{URL}{pk}/", {"name": "river"}, format="json").status_code == 409

    assert stored_formula(alice, panel) == "OakBank.spend"
    assert "OakBank" in [s.name for s in sources_for(alice, UserCipher(alice))]


def test_usage_counts_what_a_delete_touches(alice, api):
    pk = add(api, "OakBank").data["id"]
    source = DataSource.objects.get(pk=pk)
    debit = make_txn(alice, data_source=source)
    credit = make_txn(alice, data_source=first_source(alice), txn_type="credit")
    TransferLink.objects.create(user=alice, debit=debit, credit=credit)
    panel_with(alice, formula("oakbank.spend"))
    panel_with(alice, {"chart": "kpi", "y": {"measure": "spend"}, "filters": {"data_sources": [pk]}})
    panel_with(alice, formula("Main.spend"))

    assert api.get(f"{URL}{pk}/usage/").data == {"transactions": 1, "links": 1, "panels": 2}


def test_removing_moves_the_rows_when_asked(alice, api):
    pk = add(api, "OakBank").data["id"]
    row = make_txn(alice, data_source=DataSource.objects.get(pk=pk))
    target = str(first_source(alice).pk)

    body = api.post(f"{URL}{pk}/remove/", {"move_to": target}, format="json").data

    assert body == {"moved": 1, "deleted": 0}
    row.refresh_from_db()
    assert str(row.data_source_id) == target


def test_removing_deletes_the_rows_when_no_target_is_given(alice, api):
    pk = add(api, "OakBank").data["id"]
    make_txn(alice, data_source=DataSource.objects.get(pk=pk))
    assert api.post(f"{URL}{pk}/remove/", {}, format="json").data == {"moved": 0, "deleted": 1}
    assert not Transaction.objects.filter(user=alice).exists()


def test_rows_cant_move_to_another_users_source_or_the_same_one(alice, api):
    pk = add(api, "OakBank").data["id"]
    bob = make_user("bob@example.com")
    for target in (str(first_source(bob).pk), pk):
        response = api.post(f"{URL}{pk}/remove/", {"move_to": target}, format="json")
        assert response.data["code"] == "invalid_target"


def test_the_last_source_cant_be_removed(alice, api):
    [listed] = api.get(URL).data
    response = api.post(f"{URL}{listed['id']}/remove/", {}, format="json")
    assert response.data["code"] == "last_source"


def test_sources_can_be_reordered(api):
    first = api.get(URL).data[0]["id"]
    second = add(api, "OakBank").data["id"]
    assert api.post(f"{URL}reorder/", {"order": [second, first]}, format="json").status_code == 204
    assert [item["id"] for item in api.get(URL).data] == [second, first]


def test_a_reorder_must_list_every_source_once(api):
    first = api.get(URL).data[0]["id"]
    add(api, "OakBank")
    response = api.post(f"{URL}reorder/", {"order": [first]}, format="json")
    assert response.data["code"] == "invalid_order"

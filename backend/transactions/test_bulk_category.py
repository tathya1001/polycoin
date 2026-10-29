import uuid
from datetime import date

import pytest
from rest_framework.test import APIClient

from categories.models import Category
from transactions.models import Transaction
from transactions.serializers import MAX_BULK_TRANSACTIONS
from transactions.tests import make_txn, make_user

pytestmark = pytest.mark.django_db

URL = "/api/transactions/bulk-category/"


def client_for(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


def move(user, ids, category):
    body = {"transactions": [str(i) for i in ids], "category": str(category)}
    return client_for(user).post(URL, body, format="json")


@pytest.fixture
def alice():
    return make_user("alice@example.com")


@pytest.fixture
def bob():
    return make_user("bob@example.com")


def food(user):
    return Category.objects.get(user=user, name="Food")


def three(user):
    return [make_txn(user, description=f"row {i}", date=date(2026, 1, i + 1)) for i in range(3)]


def category_of(txn):
    return Transaction.objects.get(pk=txn.pk).category_id


def test_anonymous_requests_are_refused():
    res = APIClient().post(URL, {"transactions": [], "category": str(uuid.uuid4())}, format="json")
    assert res.status_code in (401, 403)


def test_many_transactions_move_into_the_category(alice):
    rows = three(alice)
    res = move(alice, [r.id for r in rows], food(alice).id)
    assert res.status_code == 200
    assert res.json() == {"updated": 3, "missing": []}
    assert all(category_of(r) == food(alice).id for r in rows)


def test_only_the_listed_transactions_move(alice):
    rows = three(alice)
    move(alice, [rows[0].id], food(alice).id)
    assert category_of(rows[0]) == food(alice).id
    assert category_of(rows[1]) != food(alice).id


def test_moving_bumps_updated_at(alice):
    row = three(alice)[0]
    before = row.updated_at
    move(alice, [row.id], food(alice).id)
    assert Transaction.objects.get(pk=row.pk).updated_at > before


def test_the_fingerprint_is_not_touched(alice):
    row = three(alice)[0]
    move(alice, [row.id], food(alice).id)
    assert bytes(Transaction.objects.get(pk=row.pk).fingerprint) == bytes(row.fingerprint)


def test_duplicate_ids_count_once(alice):
    row = three(alice)[0]
    res = move(alice, [row.id, row.id], food(alice).id)
    assert res.json()["updated"] == 1


def test_another_users_transactions_are_never_moved(alice, bob):
    bobs = three(bob)
    mine = three(alice)
    res = move(alice, [bobs[0].id, mine[0].id], food(alice).id)
    assert res.status_code == 200
    assert res.json() == {"updated": 1, "missing": [str(bobs[0].id)]}
    assert category_of(bobs[0]) != food(alice).id  # untouched


def test_unknown_ids_are_reported_like_other_users_ids(alice):
    ghost = uuid.uuid4()
    res = move(alice, [ghost], food(alice).id)
    assert res.json() == {"updated": 0, "missing": [str(ghost)]}


def test_another_users_category_is_rejected(alice, bob):
    rows = three(alice)
    res = move(alice, [r.id for r in rows], food(bob).id)
    assert res.status_code == 400
    assert "category" in res.json()
    assert all(category_of(r) != food(bob).id for r in rows)


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"transactions": []},  # nothing to move
        {"transactions": ["not-a-uuid"], "category": None},
        {"transactions": "abc", "category": None},
        {"category": None},
    ],
)
def test_malformed_requests_are_rejected(alice, body):
    if "category" in body:
        body["category"] = str(food(alice).id)
    assert client_for(alice).post(URL, body, format="json").status_code == 400


def test_there_is_a_size_limit(alice):
    ids = [uuid.uuid4() for _ in range(MAX_BULK_TRANSACTIONS + 1)]
    assert move(alice, ids, food(alice).id).status_code == 400
    assert move(alice, ids[:MAX_BULK_TRANSACTIONS], food(alice).id).status_code == 200


def test_post_on_the_list_still_cannot_create_a_transaction(alice):
    res = client_for(alice).post("/api/transactions/", {"name": "x"}, format="json")
    assert res.status_code == 405


# --- deleting -------------------------------------------------------------------------------

DELETE_URL = "/api/transactions/bulk-delete/"


def delete(user, ids):
    return client_for(user).post(DELETE_URL, {"transactions": [str(i) for i in ids]}, format="json")


def test_many_transactions_are_deleted(alice):
    rows = three(alice)
    res = delete(alice, [r.id for r in rows[:2]])
    assert res.status_code == 200
    assert res.json() == {"deleted": 2, "missing": []}
    assert list(Transaction.objects.filter(user=alice).values_list("id", flat=True)) == [rows[2].id]


def test_bulk_delete_never_touches_another_users_rows(alice, bob):
    mine, theirs = three(alice)[0], three(bob)[0]
    unknown = uuid.uuid4()
    res = delete(alice, [mine.id, theirs.id, unknown])
    assert res.json() == {"deleted": 1, "missing": sorted([str(theirs.id), str(unknown)])}
    assert Transaction.objects.filter(pk=theirs.pk).exists()


def test_bulk_delete_validates_its_input(alice):
    assert delete(alice, []).status_code == 400
    assert delete(alice, [uuid.uuid4()] * (MAX_BULK_TRANSACTIONS + 1)).status_code == 400
    bad = client_for(alice).post(DELETE_URL, {"transactions": ["nope"]}, format="json")
    assert bad.status_code == 400


def test_anonymous_bulk_delete_is_refused():
    res = APIClient().post(DELETE_URL, {"transactions": [str(uuid.uuid4())]}, format="json")
    assert res.status_code in (401, 403)

"""HTTP-level tests for the two /api/ai/ endpoints. Neither one talks to Ollama: the browser
embeds and scores with the user's own Ollama, so nothing here touches the network.
"""

import uuid

import pytest
from rest_framework.test import APIClient

from transactions.tests import make_txn, make_user

pytestmark = pytest.mark.django_db

PREPARE = "/api/ai/categorize/prepare/"
APPLY = "/api/ai/categorize/apply/"
TRANSACTIONS = "/api/transactions/"


def as_user(user):
    api = APIClient()
    api.force_authenticate(user)
    return api


def post(user, url, body):
    return as_user(user).post(url, body, format="json")


@pytest.fixture
def alice():
    return make_user("alice@example.com")


@pytest.fixture
def bob():
    return make_user("bob@example.com")


def category(user, name):
    return user.category_set.get(name=name)


# --- auth ---------------------------------------------------------------------


@pytest.mark.parametrize("method, url", [("get", PREPARE), ("post", APPLY)])
def test_every_endpoint_requires_login(method, url):
    assert getattr(APIClient(), method)(url).status_code == 401


@pytest.mark.parametrize("url", ["/api/ai/models/", "/api/ai/categorize/preview/"])
def test_the_old_server_side_ollama_endpoints_are_gone(alice, url):
    assert as_user(alice).post(url, {}, format="json").status_code == 404


# --- GET /api/ai/categorize/prepare/ ------------------------------------------


def test_prepare_returns_a_run_and_changes_nothing(alice):
    txn = make_txn(alice, name="TASTYBITES", description="UPI/DR/412345678901/TASTYBITES")

    response = as_user(alice).get(PREPARE)

    assert response.status_code == 200
    body = response.json()
    assert (body["considered"], body["capped"]) == (1, False)
    assert body["targets"][0]["transaction"] == str(txn.id)
    assert body["texts"][body["targets"][0]["text"]] == "TASTYBITES"
    txn.refresh_from_db()
    assert txn.category.is_default  # nothing was written


def test_prepare_only_ever_shows_the_callers_transactions(alice, bob):
    mine = make_txn(alice, name="TASTYBITES", description="mine")
    make_txn(bob, name="TASTYBITES", description="bobs")

    body = as_user(alice).get(PREPARE).json()

    assert [t["transaction"] for t in body["targets"]] == [str(mine.id)]


def test_prepare_is_never_cached(alice):
    # It carries decrypted narrations, so no proxy or CDN may keep a copy.
    assert "no-store" in as_user(alice).get(PREPARE)["Cache-Control"]


# --- POST /api/ai/categorize/apply/ -------------------------------------------


def test_apply_moves_the_rows_and_the_transactions_api_shows_the_new_category(alice):
    txn = make_txn(alice)
    food = category(alice, "Food")

    response = post(alice, APPLY, {"decisions": [{"transaction": str(txn.id), "category": str(food.id)}]})

    assert response.status_code == 200
    assert response.json() == {"applied": 1, "skipped": []}
    row = as_user(alice).get(TRANSACTIONS).json()["results"][0]
    assert row["category"] == str(food.id)
    assert "categorized_by" not in row  # an approved proposal is just the user's decision


def test_apply_skips_another_users_transaction_and_category(alice, bob):
    victim = make_txn(bob)
    own = make_txn(alice, name="own", description="x")
    decisions = [
        {"transaction": str(victim.id), "category": str(category(alice, "Food").id)},
        {"transaction": str(own.id), "category": str(category(bob, "Food").id)},
    ]

    response = post(alice, APPLY, {"decisions": decisions})

    assert response.json() == {
        "applied": 0,
        "skipped": [
            {"transaction": str(victim.id), "reason": "not_in_others"},
            {"transaction": str(own.id), "reason": "invalid_category"},
        ],
    }
    victim.refresh_from_db()
    own.refresh_from_db()
    assert victim.category.is_default and own.category.is_default


def a_decision():
    return {"transaction": str(uuid.uuid4()), "category": str(uuid.uuid4())}


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"decisions": []},
        {"decisions": "not-a-list"},
        {"decisions": [{"transaction": "not-a-uuid", "category": str(uuid.uuid4())}]},
        {"decisions": [{"transaction": str(uuid.uuid4())}]},
    ],
)
def test_apply_rejects_malformed_requests(alice, payload):
    response = post(alice, APPLY, payload)

    assert response.status_code == 400
    assert "decisions" in response.json()


def test_apply_rejects_more_decisions_than_a_run_can_produce(alice, settings):
    too_many = [a_decision() for _ in range(settings.AI_MAX_RUN + 1)]

    response = post(alice, APPLY, {"decisions": too_many})

    assert response.status_code == 400


# --- throttling ---------------------------------------------------------------


def test_prepare_has_its_own_tight_budget_that_apply_does_not_share(alice):
    api = as_user(alice)

    codes = [api.get(PREPARE).status_code for _ in range(21)]

    assert codes[:20] == [200] * 20
    assert codes[20] == 429
    assert api.post(APPLY, {"decisions": [a_decision()]}, format="json").status_code == 200

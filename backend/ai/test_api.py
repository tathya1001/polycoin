"""HTTP-level tests for the three /api/ai/ endpoints. Ollama is replaced by the fakes from
test_services.py (`ai.views.get_client` is the single seam), so nothing touches the network.
"""

import uuid

import pytest
from rest_framework.test import APIClient

from ai.client import AIError
from ai.test_services import FakeOllama
from transactions.tests import make_txn, make_user

pytestmark = pytest.mark.django_db

MODELS = "/api/ai/models/"
PREVIEW = "/api/ai/categorize/preview/"
APPLY = "/api/ai/categorize/apply/"
TRANSACTIONS = "/api/transactions/"


class BrokenOllama:
    """Fails the way a real Ollama can: at listing time, or while embedding."""

    def __init__(self, code, *, on):
        self.code, self.on = code, on

    def list_models(self):
        if self.on == "list_models":
            raise AIError(self.code, "boom")
        return [{"name": "fake-model", "dimension": 11}]

    def embed(self, model, texts):
        raise AIError(self.code, "boom")


def use_client(monkeypatch, client):
    monkeypatch.setattr("ai.views.get_client", lambda: client)
    return client


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


@pytest.fixture
def ollama(monkeypatch):
    return use_client(monkeypatch, FakeOllama())


def category(user, name):
    return user.category_set.get(name=name)


# --- auth ---------------------------------------------------------------------


@pytest.mark.parametrize("method, url", [("get", MODELS), ("post", PREVIEW), ("post", APPLY)])
def test_every_endpoint_requires_login(method, url):
    assert getattr(APIClient(), method)(url).status_code == 401


# --- GET /api/ai/models/ ------------------------------------------------------


def test_models_lists_the_installed_embedders(alice, ollama):
    response = as_user(alice).get(MODELS)

    assert response.status_code == 200
    assert response.json() == {"models": [{"name": "fake-model", "dimension": 11}]}


@pytest.mark.parametrize(
    "code, expected_status",
    [
        ("ollama_unreachable", 503),
        ("no_embedding_models", 400),
        ("embedding_failed", 502),
        ("dimension_mismatch", 502),
        ("model_not_found", 400),
    ],
)
def test_ai_errors_become_typed_responses_never_500s(alice, monkeypatch, code, expected_status):
    use_client(monkeypatch, BrokenOllama(code, on="list_models"))

    response = as_user(alice).get(MODELS)

    assert response.status_code == expected_status
    assert response.json() == {"code": code, "detail": "boom"}


# --- POST /api/ai/categorize/preview/ -----------------------------------------


def test_preview_returns_proposals_and_changes_nothing(alice, ollama):
    txn = make_txn(alice, name="TASTYBITES", description="UPI/DR/412345678901/TASTYBITES")

    response = post(alice, PREVIEW, {"model": "fake-model"})

    assert response.status_code == 200
    body = response.json()
    assert body["model"] == "fake-model"
    assert (body["considered"], body["proposed"], body["skipped"], body["capped"]) == (1, 1, 0, False)
    row = body["proposals"][0]
    assert row["transaction"] == str(txn.id)
    assert row["category_name"] == "Food"
    assert row["decision"] == "propose"
    txn.refresh_from_db()
    assert txn.category.is_default


@pytest.mark.parametrize(
    "payload, field",
    [
        ({}, "model"),
        ({"model": ""}, "model"),
    ],
)
def test_preview_rejects_malformed_requests(alice, ollama, payload, field):
    response = post(alice, PREVIEW, payload)

    assert response.status_code == 400
    assert field in response.json()
    assert ollama.calls == []


def test_preview_refuses_a_model_that_is_not_installed(alice, ollama):
    make_txn(alice, name="TASTYBITES", description="a")

    response = post(alice, PREVIEW, {"model": "not-installed"})

    assert response.status_code == 400
    assert response.json()["code"] == "model_not_found"
    assert ollama.calls == []  # the string never reached Ollama


def test_preview_ignores_attempts_to_choose_the_ollama_address(alice, ollama):
    response = post(alice, PREVIEW, {"model": "fake-model", "base_url": "http://evil.test"})

    assert response.status_code == 200  # extra keys are simply not read


def test_preview_only_ever_shows_the_callers_transactions(alice, bob, ollama):
    mine = make_txn(alice, name="TASTYBITES", description="mine")
    make_txn(bob, name="TASTYBITES", description="bobs")

    body = post(alice, PREVIEW, {"model": "fake-model"}).json()

    assert [row["transaction"] for row in body["proposals"]] == [str(mine.id)]


def test_preview_reports_ollama_being_down_as_503(alice, monkeypatch):
    use_client(monkeypatch, BrokenOllama("ollama_unreachable", on="list_models"))

    response = post(alice, PREVIEW, {"model": "fake-model"})

    assert response.status_code == 503
    assert response.json()["code"] == "ollama_unreachable"


def test_preview_reports_an_embedding_failure_as_502(alice, monkeypatch):
    make_txn(alice, name="TASTYBITES", description="a")
    use_client(monkeypatch, BrokenOllama("embedding_failed", on="embed"))

    response = post(alice, PREVIEW, {"model": "fake-model"})

    assert response.status_code == 502
    assert response.json()["code"] == "embedding_failed"


# --- POST /api/ai/categorize/apply/ -------------------------------------------


def test_apply_moves_the_rows_and_the_transactions_api_shows_the_new_category(alice, ollama):
    txn = make_txn(alice)
    food = category(alice, "Food")

    response = post(alice, APPLY, {"decisions": [{"transaction": str(txn.id), "category": str(food.id)}]})

    assert response.status_code == 200
    assert response.json() == {"applied": 1, "skipped": []}
    row = as_user(alice).get(TRANSACTIONS).json()["results"][0]
    assert row["category"] == str(food.id)
    assert "categorized_by" not in row  # an approved proposal is just the user's decision


def test_apply_works_even_when_ollama_is_down(alice, monkeypatch):
    use_client(monkeypatch, BrokenOllama("ollama_unreachable", on="list_models"))
    txn = make_txn(alice)
    food = category(alice, "Food")

    response = post(alice, APPLY, {"decisions": [{"transaction": str(txn.id), "category": str(food.id)}]})

    assert response.status_code == 200
    assert response.json()["applied"] == 1


def test_apply_skips_another_users_transaction_and_category(alice, bob, ollama):
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
def test_apply_rejects_malformed_requests(alice, ollama, payload):
    response = post(alice, APPLY, payload)

    assert response.status_code == 400
    assert "decisions" in response.json()


def test_apply_rejects_more_decisions_than_a_preview_can_produce(alice, ollama, settings):
    too_many = [a_decision() for _ in range(settings.AI_MAX_RUN + 1)]

    response = post(alice, APPLY, {"decisions": too_many})

    assert response.status_code == 400


# --- throttling ---------------------------------------------------------------


def test_preview_has_its_own_tight_budget_that_apply_and_models_do_not_share(alice, ollama):
    api = as_user(alice)

    codes = [api.post(PREVIEW, {"model": "fake-model"}, format="json").status_code for _ in range(21)]

    assert codes[:20] == [200] * 20
    assert codes[20] == 429
    assert api.get(MODELS).status_code == 200
    assert api.post(APPLY, {"decisions": [a_decision()]}, format="json").status_code == 200

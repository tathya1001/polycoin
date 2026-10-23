"""HTTP-level tests for the /api/ai/rag/ endpoints. Nothing here calls Ollama: the browser embeds
with the user's own Ollama, so the tests send the vectors a browser would."""

import logging
import os
from datetime import date

import pytest
from rest_framework.test import APIClient

from ai.models import RagDocument
from ai.rag.profiles import PROMPT_VERSION
from ai.rag_views import AskView, IndexView, PendingView, StatusView, VectorsView
from ai.test_rag_retriever import NEAR_GYM, VECTORS
from categories.models import Category
from transactions.tests import make_txn, make_user

pytestmark = pytest.mark.django_db

BASE = "/api/ai/rag"
MODEL, DIGEST = "test-embed:latest", "sha256:aaaa"
MODEL_QUERY = f"?model={MODEL}&digest={DIGEST}"


def as_user(user):
    api = APIClient()
    api.force_authenticate(user)
    return api


@pytest.fixture
def alice():
    return make_user("alice@example.com")


@pytest.fixture
def bob():
    return make_user("bob@example.com")


def history(user):
    health = Category.objects.get(user=user, name="Health")
    food = Category.objects.get(user=user, name="Food")
    return {
        "gym": make_txn(user, name="Fitzone Gym", description="UPI/FITZONE/jan",
                        date=date(2026, 1, 5), category=health),
        "cafe": make_txn(user, name="Tastybites Cafe", description="UPI/TASTYBITES/feb",
                         date=date(2026, 2, 1), category=food),
    }  # fmt: skip


def embed(items):
    """What the browser sends back: a vector per pending item, from the merchant in its text."""
    return [
        {
            "transaction": item["transaction"],
            "version": item["version"],
            "vector": next(v for name, v in VECTORS.items() if name in item["text"]),
        }
        for item in items
    ]


def index_over_http(api):
    pending = api.get(f"{BASE}/pending/{MODEL_QUERY}").json()
    body = {"model": MODEL, "digest": DIGEST, "items": embed(pending["items"])}
    return api.post(f"{BASE}/vectors/", body, format="json")


def ask(api, question="gym", vector=NEAR_GYM, **extra):
    body = {"model": MODEL, "digest": DIGEST, "question": question, "vector": vector, **extra}
    return api.post(f"{BASE}/ask/", body, format="json")


# --- the whole flow ---------------------------------------------------------------


def test_index_then_ask_end_to_end(alice):
    rows = history(alice)
    api = as_user(alice)

    assert api.get(f"{BASE}/status/{MODEL_QUERY}").json()["indexed"] == 0
    stored = index_over_http(api)
    assert stored.status_code == 200 and stored.json() == {"stored": 2, "stale": 0, "rejected": 0}
    assert api.get(f"{BASE}/status/{MODEL_QUERY}").json() == {
        "enabled": True,
        "indexed": 2,
        "total": 2,
        "profile": {"doc_prefix": "", "query_prefix": "", "tuned": False},
    }

    response = ask(api, "What do I pay for the gym?")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "prompt_version", "profile", "period", "coverage", "summary", "sources", "in_prompt",
        "messages",
        "options",
    }  # fmt: skip
    assert body["sources"][0]["transaction"] == str(rows["gym"].id)
    assert body["sources"][0]["amount"] == "4.50"
    assert [m["role"] for m in body["messages"]] == ["system", "user"]
    assert body["options"] == {"temperature": 0.1, "num_ctx": 4096}
    assert body["coverage"] == {"searched": 2, "indexed": 2, "total": 2}


def test_a_question_with_a_date_phrase_reports_the_period_it_searched(alice):
    history(alice)
    api = as_user(alice)
    index_over_http(api)

    period = ask(api, "gym in January 2026").json()["period"]
    assert period == {
        "from": "2026-01-01",
        "to": "2026-01-31",
        "source": "question",
        "phrase": "in January 2026",
    }
    period = ask(api, "gym in January 2026", use_question_period=False).json()["period"]
    assert period["source"] == "filter" and period["phrase"] is None


def test_no_matches_means_no_messages_for_the_model(alice, monkeypatch):
    from ai.rag import retriever
    from ai.rag.profiles import Profile

    history(alice)
    api = as_user(alice)
    index_over_http(api)
    monkeypatch.setattr(retriever, "profile_for", lambda model: Profile("", "", 0.99))

    body = ask(api, "how much did I spend?", vector=[0.5, 0.5, 0.5, 0.5]).json()
    assert body["messages"] is None and body["sources"] == []


def test_clear_deletes_the_index(alice):
    history(alice)
    api = as_user(alice)
    index_over_http(api)

    assert api.delete(f"{BASE}/index/").status_code == 204
    assert not RagDocument.objects.filter(user=alice).exists()


# --- isolation --------------------------------------------------------------------


def test_one_user_can_never_search_or_store_into_another_users_data(alice, bob):
    rows = history(alice)
    index_over_http(as_user(alice))
    history(bob)
    index_over_http(as_user(bob))

    sources = ask(as_user(bob), "gym").json()["sources"]
    assert str(rows["gym"].id) not in {source["transaction"] for source in sources}

    theirs = {"transaction": str(rows["cafe"].id), "version": "x", "vector": [0.0, 1.0, 0.0, 0.0]}
    body = {"model": MODEL, "digest": DIGEST, "items": [theirs]}
    stored = as_user(bob).post(f"{BASE}/vectors/", body, format="json").json()
    assert stored == {"stored": 0, "stale": 0, "rejected": 1}


def test_every_endpoint_needs_a_login():
    anonymous = APIClient()
    for method, path in [
        ("get", f"/status/{MODEL_QUERY}"),
        ("get", f"/pending/{MODEL_QUERY}"),
        ("post", "/vectors/"),
        ("post", "/ask/"),
        ("delete", "/index/"),
    ]:
        assert getattr(anonymous, method)(f"{BASE}{path}").status_code in (401, 403)


# --- validation and errors --------------------------------------------------------


@pytest.mark.parametrize(
    "vector",
    [[], [True, 0.5], ["0.5"], [[0.5]], "0.5", None, [0.5] * 4097],
    ids=["empty", "bool", "string", "nested", "not-a-list", "null", "too-long"],
)
def test_a_vector_must_be_a_flat_list_of_numbers(alice, vector):
    response = ask(as_user(alice), vector=vector)
    assert response.status_code == 400 and "vector" in response.json()


def test_nan_is_refused_by_the_strict_json_parser(alice):
    raw = f'{{"model": "{MODEL}", "digest": "{DIGEST}", "question": "gym", "vector": [NaN, 1]}}'
    response = as_user(alice).post(f"{BASE}/ask/", raw, content_type="application/json")
    assert response.status_code == 400


@pytest.mark.parametrize("question", ["", "   ", "x" * 301])
def test_a_question_must_have_one_to_three_hundred_characters(alice, question):
    response = ask(as_user(alice), question=question)
    assert response.status_code == 400 and "question" in response.json()


def test_service_errors_use_the_apps_code_and_detail_body(alice):
    history(alice)
    api = as_user(alice)

    no_index = ask(api)
    assert no_index.status_code == 400 and no_index.json()["code"] == "no_index"

    index_over_http(api)
    for response, code in [
        (ask(api, vector=[1.0, 0.0, 0.0]), "dimension_mismatch"),
        (ask(api, vector=[0.0, 0.0, 0.0, 0.0]), "invalid_vector"),
        (ask(api, filters={"type": "refund"}), "invalid_filters"),
    ]:
        assert response.status_code == 400
        assert set(response.json()) == {"code", "detail"} and response.json()["code"] == code


def test_pending_caps_the_limit_at_the_batch_size(alice, settings):
    settings.RAG_INDEX_BATCH = 1
    history(alice)
    api = as_user(alice)

    assert len(api.get(f"{BASE}/pending/{MODEL_QUERY}&limit=50").json()["items"]) == 1
    assert api.get(f"{BASE}/pending/{MODEL_QUERY}&limit=0").status_code == 400
    assert api.get(f"{BASE}/pending/?model={MODEL}").status_code == 400  # digest is required


def test_vectors_refuses_a_batch_over_the_batch_size(alice, settings):
    settings.RAG_INDEX_BATCH = 1
    rows = history(alice)
    items = [
        {"transaction": str(txn.id), "version": txn.updated_at.isoformat(), "vector": [1.0, 0.0]}
        for txn in rows.values()
    ]
    body = {"model": MODEL, "digest": DIGEST, "items": items}
    assert as_user(alice).post(f"{BASE}/vectors/", body, format="json").status_code == 400


def test_a_full_batch_of_768_dimension_vectors_fits_in_one_request(alice):
    for n in range(100):
        make_txn(alice, name=f"Shop{n}", description=f"UPI/SHOP{n}/x")
    api = as_user(alice)
    pending = api.get(f"{BASE}/pending/{MODEL_QUERY}").json()["items"]
    items = [
        {"transaction": item["transaction"], "version": item["version"], "vector": [0.036] * 768}
        for item in pending
    ]
    body = {"model": MODEL, "digest": DIGEST, "items": items}  # about 0.5 MB of JSON
    assert api.post(f"{BASE}/vectors/", body, format="json").json()["stored"] == 100


# --- the kill switch --------------------------------------------------------------


def test_turned_off_the_feature_refuses_work_but_explains_and_still_deletes(alice, settings):
    history(alice)
    api = as_user(alice)
    index_over_http(api)
    settings.RAG_ENABLED = False

    for response in (
        api.get(f"{BASE}/pending/{MODEL_QUERY}"),
        api.post(f"{BASE}/vectors/", {}, format="json"),
        ask(api),
    ):
        assert response.status_code == 503 and response.json()["code"] == "rag_disabled"
    assert api.get(f"{BASE}/status/{MODEL_QUERY}").json()["enabled"] is False
    assert api.delete(f"{BASE}/index/").status_code == 204


# --- privacy ----------------------------------------------------------------------


def test_the_ask_log_line_has_counts_and_never_the_question_or_the_data(alice, caplog):
    history(alice)
    api = as_user(alice)
    index_over_http(api)

    with caplog.at_level(logging.INFO):
        ask(api, "What do I pay for my secret gym membership?")

    assert f"rag ask: prompt={PROMPT_VERSION}" in caplog.text and "matches=" in caplog.text
    for secret in ("secret", "membership", "Fitzone", "FITZONE", "4.50"):
        assert secret not in caplog.text


def test_responses_are_never_cached(alice):
    history(alice)
    response = as_user(alice).get(f"{BASE}/pending/{MODEL_QUERY}")
    assert "no-store" in response["Cache-Control"]


def test_langsmith_tracing_is_forced_off():
    import langsmith.utils

    for name in ("LANGSMITH_TRACING", "LANGCHAIN_TRACING_V2"):
        assert os.environ[name] == "false"
    assert "LANGSMITH_API_KEY" not in os.environ and "LANGCHAIN_API_KEY" not in os.environ
    assert langsmith.utils.tracing_is_enabled() is False


def test_each_endpoint_has_its_throttle_scope_and_the_scopes_have_rates(settings):
    scopes = {
        StatusView: "ai_light",
        PendingView: "rag_index",
        VectorsView: "rag_index",
        AskView: "rag_ask",
        IndexView: "destructive",
    }
    rates = settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]
    for view, scope in scopes.items():
        assert view.throttle_scope == scope and scope in rates

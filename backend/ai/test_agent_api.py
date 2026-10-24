"""HTTP-level tests for /api/ai/agent/. Nothing here calls Ollama: the tests send the replies a
browser would relay from the user's model."""

import json
import logging
from decimal import Decimal

import pytest
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework.throttling import ScopedRateThrottle

from ai.agent.prompts import PROMPT_VERSION
from ai.agent_views import MAX_MESSAGE, StatusView, StepView, TurnView
from transactions.tests import make_txn, make_user

pytestmark = pytest.mark.django_db

BASE = "/api/ai/agent"
BAR = json.dumps({"kind": "panel", "chart": "bar", "measure": "spend", "x": "category"})


def as_user(user):
    api = APIClient()
    api.force_authenticate(user)
    return api


@pytest.fixture
def alice():
    user = make_user("alice@example.com")
    make_txn(user, name="Tastybites Cafe", date=timezone.localdate(), amount=Decimal("4.50"))
    return user


@pytest.fixture
def bob():
    return make_user("bob@example.com")


def turn(api, message="spend by category", **extra):
    return api.post(f"{BASE}/turn/", {"message": message, **extra}, format="json")


def step(api, token, **answer):
    return api.post(f"{BASE}/step/", {"token": token, **answer}, format="json")


def problem(response) -> str:
    assert response.status_code == 400, response.content
    return response.json()["code"]


# --- the whole flow -------------------------------------------------------------------


def test_turn_then_step_previews_a_panel(alice):
    api = as_user(alice)
    first = turn(api, dashboard={"filters": {"date": {"preset": "this_month"}}})
    assert first.status_code == 200 and first.json()["status"] == "needs_model"
    request = first.json()["request"]
    assert request["kind"] == "chat" and request["options"]["temperature"] == 0

    done = step(api, first.json()["token"], reply=BAR)
    assert done.status_code == 200
    body = done.json()
    assert body["status"] == "done" and body["outcome"]["kind"] == "preview"
    assert body["outcome"]["config"]["chart"] == "bar" and body["token"]


def test_a_follow_up_turn_carries_the_token(alice):
    api = as_user(alice)
    done = step(api, turn(api).json()["token"], reply=BAR).json()
    follow = turn(api, "make it a line", token=done["token"])
    assert follow.json()["progress"]["label"] == "Changing the panel"


def test_status_says_what_the_page_needs(alice):
    body = as_user(alice).get(f"{BASE}/status/").json()
    assert body == {
        "enabled": True,
        "prompt_version": PROMPT_VERSION,
        "limits": {"message": MAX_MESSAGE, "reply": 4000, "turns": 12, "steps": 6},
    }


def test_responses_are_never_cached(alice):
    response = turn(as_user(alice))
    assert "no-store" in response["Cache-Control"]


# --- the kill switch and access -------------------------------------------------------------


def test_turned_off_the_builder_answers_503_but_status_still_works(alice, settings):
    settings.AGENT_ENABLED = False
    api = as_user(alice)
    assert api.get(f"{BASE}/status/").json()["enabled"] is False
    for response in (turn(api), step(api, "x.y", reply=BAR)):
        assert response.status_code == 503 and response.json()["code"] == "agent_disabled"


def test_every_endpoint_needs_a_signed_in_user():
    api = APIClient()
    for response in (api.get(f"{BASE}/status/"), turn(api), step(api, "x.y", reply=BAR)):
        assert response.status_code in (401, 403)


def test_another_users_token_is_refused(alice, bob):
    token = turn(as_user(alice)).json()["token"]
    assert problem(step(as_user(bob), token, reply=BAR)) == "token_invalid"
    assert problem(turn(as_user(bob), token=token)) == "token_invalid"


def test_each_endpoint_has_its_throttle_scope_and_the_scopes_have_rates(settings):
    scopes = {StatusView: "ai_light", TurnView: "agent", StepView: "agent"}
    rates = settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]
    for view, scope in scopes.items():
        assert view.throttle_scope == scope and scope in rates
        assert ScopedRateThrottle in [type(t) for t in view().get_throttles()]


# --- validation -----------------------------------------------------------------------------


@pytest.mark.parametrize("message", ["", "   ", "x" * (MAX_MESSAGE + 1)])
def test_a_message_must_be_short_text(alice, message):
    assert turn(as_user(alice), message).status_code == 400


def test_a_bad_dashboard_or_embedding_model_is_refused(alice):
    api = as_user(alice)
    assert problem(turn(api, dashboard={"filters": {"type": "sideways"}})) == "invalid_filters"
    assert turn(api, embed={"model": "only-a-name"}).status_code == 400


@pytest.mark.parametrize(
    "answer",
    [{}, {"skip": False}, {"reply": BAR, "vector": [0.1]}, {"reply": BAR, "skip": True}],
)
def test_a_step_sends_exactly_one_answer(alice, answer):
    token = turn(as_user(alice)).json()["token"]
    assert step(as_user(alice), token, **answer).status_code == 400


def test_a_reply_and_a_vector_are_size_capped(alice, settings):
    api = as_user(alice)
    token = turn(api).json()["token"]
    assert step(api, token, reply="x" * 4001).status_code == 400
    assert step(api, token, vector=[0.1] * (settings.RAG_MAX_DIMS + 1)).status_code == 400
    assert step(api, token, vector=[True]).status_code == 400


def test_an_oversized_token_is_refused_before_anything_else(alice, settings):
    oversized = "x" * (settings.AGENT_MAX_TOKEN_BYTES + 1)
    assert problem(step(as_user(alice), oversized, reply=BAR)) == "token_invalid"


def test_a_wrong_step_is_a_400_with_a_code(alice):
    api = as_user(alice)
    token = turn(api).json()["token"]
    assert problem(step(api, token, vector=[0.1, 0.2])) == "unexpected_step"


def test_a_cap_is_a_400_with_a_code(alice, settings):
    settings.AGENT_MAX_TURNS = 1
    api = as_user(alice)
    done = step(api, turn(api).json()["token"], reply=BAR).json()
    assert problem(turn(api, "again", token=done["token"])) == "too_many_turns"


# --- logs -----------------------------------------------------------------------------------


def test_the_log_line_has_counts_but_no_content(alice, caplog):
    api = as_user(alice)
    with caplog.at_level(logging.INFO, logger="ai.agent.service"):
        token = turn(api, "secret spend at tastybites", dashboard={}).json()["token"]
        step(api, token, reply=BAR)
    assert f"agent turn: prompt={PROMPT_VERSION} result=chat code=-" in caplog.text
    assert "agent step:" in caplog.text and "result=preview" in caplog.text
    for secret in ("secret", "tastybites", "Tastybites", "4.50", "category", token[:20]):
        assert secret not in caplog.text

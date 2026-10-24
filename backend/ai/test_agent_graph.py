"""The panel builder's workflow, driven through the service with canned model replies, the way
the browser relays them. Nothing here calls a model."""

import json
import threading
from datetime import date
from decimal import Decimal

import pytest
from django.utils import timezone

from ai.agent import compile as compiler
from ai.agent import service
from ai.agent.errors import AgentError
from ai.agent.graph import BUILDER, GRAPH_VERSION
from ai.agent.schema import ollama_schema
from ai.agent.sealed import unseal
from ai.test_rag_retriever import DIGEST, MODEL, NEAR_GYM
from ai.test_rag_retriever import history as indexed_history
from transactions.tests import make_txn, make_user

pytestmark = pytest.mark.django_db

EMBED = {"model": MODEL, "digest": DIGEST}
SKIP = object()


def reply(**fields) -> str:
    return json.dumps({"kind": "panel", **fields})


BAR = reply(chart="bar", measure="spend", x="category")
LINE = reply(chart="line", measure="spend", x="date", granularity="week")
BROKEN = '{"kind": "panel", "chart": '


@pytest.fixture
def alice():
    user = make_user("alice@example.com")
    make_txn(user, date=timezone.localdate(), amount=Decimal("12.00"))
    return user


@pytest.fixture
def indexed():
    """A user whose five fictional transactions are in the "Ask" index (and nothing else)."""
    user = make_user("carol@example.com")
    indexed_history(user)
    return user


def converse(user, message, answers, token=None, dashboard=None, embed=None) -> list[dict]:
    """One turn: the message, then each canned answer the browser would relay."""
    responses = [service.turn(user, message, token, dashboard or {}, embed)]
    answers = list(answers)
    while responses[-1]["status"] == "needs_model":
        last, answer = responses[-1], answers.pop(0)
        if last["request"]["kind"] == "chat":
            responses.append(service.step(user, last["token"], reply=answer))
        elif answer is SKIP:
            responses.append(service.step(user, last["token"], skip=True))
        else:
            responses.append(service.step(user, last["token"], vector=answer))
    assert not answers, "the turn ended before every answer was used"
    return responses


def outcome(responses) -> dict:
    assert responses[-1]["status"] == "done"
    return responses[-1]["outcome"]


def last_message(response) -> str:
    return response["request"]["messages"][-1]["content"]


def state_of(user, token) -> dict:
    saver = unseal(user, token, GRAPH_VERSION)
    graph = BUILDER.compile(checkpointer=saver)
    return graph.get_state({"configurable": {"thread_id": saver.thread_id}}).values


# --- one request, one panel ------------------------------------------------------------


def test_a_request_becomes_a_previewed_panel(alice):
    responses = converse(alice, "spend by category", [BAR])
    first = responses[0]
    assert first["progress"] == {"label": "Reading your request", "attempt": 1}
    assert first["request"]["kind"] == "chat" and first["request"]["format"] == ollama_schema()
    assert last_message(first) == "<request>spend by category</request>"

    shown = outcome(responses)
    assert shown["kind"] == "preview" and shown["config"]["chart"] == "bar"
    assert shown["title"] == shown["summary"] == "Spend by category · Dashboard period · Bar"
    assert shown["result"]["rows"] and shown["notes"] == []


def test_the_models_title_is_used(alice):
    shown = outcome(converse(alice, "spend", [reply(chart="kpi", measure="spend", title="Out")]))
    assert shown["title"] == "Out" and shown["summary"].startswith("Spend")


def test_a_question_is_not_a_panel(alice):
    answer = json.dumps({"kind": "not_a_panel", "reason": "That is a question."})
    responses = converse(alice, "why did I spend so much?", [answer])
    assert outcome(responses) == {"kind": "not_a_panel", "reason": "That is a question."}
    # No panel yet, so the next message is a fresh request, not a change.
    follow = service.turn(alice, "spend by category", responses[-1]["token"], {}, None)
    assert follow["progress"]["label"] == "Reading your request"


def test_a_date_phrase_in_the_message_wins(alice):
    responses = converse(alice, "spend by category last month", [reply(
        chart="bar", measure="spend", x="category", period="this_year")])  # fmt: skip
    assert outcome(responses)["config"]["filters"]["date"] == {"preset": "last_month"}


def test_the_panel_uses_the_dashboards_filters(alice):
    dashboard = {"filters": {"date": {"preset": "this_month"}}}
    shown = outcome(
        converse(alice, "spend", [reply(chart="kpi", measure="spend")], dashboard=dashboard)
    )
    assert shown["result"]["period"]["from"] == timezone.localdate().replace(day=1).isoformat()


def test_a_bad_dashboard_filter_is_refused(alice):
    with pytest.raises(AgentError) as caught:
        service.turn(alice, "spend", None, {"filters": {"type": "sideways"}}, None)
    assert caught.value.code == "invalid_filters"


# --- repairs ----------------------------------------------------------------------------


def test_a_broken_reply_is_repaired(alice):
    responses = converse(alice, "spend by category", [BROKEN, BAR])
    repair = responses[1]
    assert repair["progress"] == {"label": "Fixing the panel", "attempt": 2}
    assert "could not be used" in last_message(repair) and "<panel>" not in last_message(repair)
    assert outcome(responses)["kind"] == "preview"


def test_a_panel_the_rules_refuse_is_repaired_with_the_reason(alice):
    pie_of_net = reply(chart="pie", measure="net", x="category")
    responses = converse(alice, "net by category", [pie_of_net, BAR])
    message = last_message(responses[1])
    assert '"measure":"net"' in message and "never negative" in message
    assert outcome(responses)["config"]["chart"] == "bar"


def test_repairs_stop_at_the_limit(alice, settings):
    settings.AGENT_MAX_REPAIRS = 2
    responses = converse(alice, "spend", [BROKEN, BROKEN, BROKEN])
    failed = outcome(responses)
    assert failed["kind"] == "failed" and failed["code"] == "no_valid_panel"
    assert failed["detail"].startswith("The model could not make this panel. reply:")


def test_a_preview_that_cannot_be_drawn_goes_back_to_the_model(alice, monkeypatch):
    monkeypatch.setattr(compiler, "MAX_COARSEN", 0)
    make_txn(alice, date=date(2020, 1, 1), description="old")
    daily = reply(chart="line", measure="spend", x="date", granularity="day", period="all")
    monthly = reply(chart="line", measure="spend", x="date", granularity="month", period="all")
    responses = converse(alice, "spend over time", [daily, monthly])
    assert "could not be drawn" in last_message(responses[1])
    assert outcome(responses)["config"]["x"]["granularity"] == "month"


def test_too_many_rows_ends_the_turn_with_the_panel_to_edit(alice, settings):
    settings.INSIGHTS_MAX_ROWS = 0
    failed = outcome(converse(alice, "spend", [BAR]))
    assert failed["kind"] == "failed" and failed["code"] == "too_many_rows"
    assert failed["config"]["chart"] == "bar" and failed["title"]


# --- follow-ups -------------------------------------------------------------------------


def test_a_follow_up_changes_the_same_panel(alice):
    first = converse(alice, "spend by category", [BAR])
    second = converse(alice, "make it a weekly line", [LINE], token=first[-1]["token"])
    ask = second[0]
    assert ask["progress"]["label"] == "Changing the panel"
    assert '<panel>{"kind":"panel","chart":"bar"' in last_message(ask)
    assert outcome(second)["config"]["chart"] == "line"


def test_a_repair_never_shows_the_current_panel_as_the_models_reply(alice):
    first = converse(alice, "spend by category", [BAR])
    waiting = service.turn(alice, "make it a line", first[-1]["token"], {}, None)
    repair = service.step(alice, waiting["token"], reply=BROKEN)
    assert repair["progress"]["label"] == "Fixing the panel"
    assert "<panel>" not in last_message(repair)  # the reply didn't parse: nothing to show


def test_a_failed_follow_up_keeps_the_last_good_panel(alice, settings):
    settings.AGENT_MAX_REPAIRS = 0
    first = converse(alice, "spend by category", [BAR])
    failed = converse(alice, "something odd", [BROKEN], token=first[-1]["token"])
    assert outcome(failed)["kind"] == "failed"
    again = service.turn(alice, "make it a line", failed[-1]["token"], {}, None)
    assert '"chart":"bar"' in last_message(again)


def test_a_new_message_while_waiting_starts_that_turn_over(alice):
    waiting = service.turn(alice, "spend by category", None, {}, None)
    restarted = service.turn(alice, "income by month", waiting["token"], {}, None)
    assert last_message(restarted) == "<request>income by month</request>"
    assert state_of(alice, restarted["token"])["turns"] == 2


# --- merchants --------------------------------------------------------------------------


def test_a_merchant_by_name_needs_no_embedding(alice):
    make_txn(alice, name="Tastybites Cafe", description="lunch", date=timezone.localdate())
    shown = outcome(converse(alice, "tasty spend", [reply(chart="kpi", merchant="tastybites")]))
    assert shown["config"]["filters"]["merchant_contains"] == "tastybites"


def test_an_unknown_merchant_is_found_by_meaning(indexed):
    responses = converse(
        indexed,
        "workout spend",
        [reply(chart="kpi", measure="spend", merchant="workout"), NEAR_GYM],
        embed=EMBED,
    )
    embed = responses[1]
    assert embed["request"] == {"kind": "embed", "model": MODEL, "text": "workout"}
    assert embed["progress"] == {"label": "Looking up the merchant", "attempt": 1}
    shown = outcome(responses)
    assert shown["config"]["filters"]["merchant_contains"] == "fitzone gym"
    assert any("matched by meaning" in note for note in shown["notes"])


def test_a_browser_without_an_embedder_skips_the_search(indexed):
    answers = [reply(chart="kpi", measure="spend", merchant="workout"), SKIP]
    shown = outcome(converse(indexed, "workout spend", answers, embed=EMBED))
    assert shown["config"]["filters"]["merchant_contains"] == ""
    assert any("not filtered by merchant" in note for note in shown["notes"])


def test_without_an_index_an_unknown_merchant_is_only_a_note(alice):
    shown = outcome(converse(alice, "spend", [reply(chart="kpi", merchant="workout")], embed=EMBED))
    assert shown["config"]["filters"]["merchant_contains"] == ""


# --- caps and wrong steps ------------------------------------------------------------------


def test_a_conversation_has_a_turn_limit(alice, settings):
    settings.AGENT_MAX_TURNS = 1
    first = converse(alice, "spend by category", [BAR])
    with pytest.raises(AgentError) as caught:
        service.turn(alice, "make it a line", first[-1]["token"], {}, None)
    assert caught.value.code == "too_many_turns"


def test_a_turn_has_a_step_limit(alice, settings):
    settings.AGENT_MAX_REPAIRS, settings.AGENT_MAX_STEPS = 5, 2
    second = service.step(
        alice, service.turn(alice, "spend", None, {}, None)["token"], reply=BROKEN
    )
    with pytest.raises(AgentError) as caught:
        service.step(alice, second["token"], reply=BROKEN)
    assert caught.value.code == "too_many_steps"


def test_a_step_with_nothing_waiting_is_refused(alice):
    done = converse(alice, "spend by category", [BAR])[-1]
    with pytest.raises(AgentError) as caught:
        service.step(alice, done["token"], reply=BAR)
    assert caught.value.code == "unexpected_step"


def test_a_step_of_the_wrong_kind_is_refused(indexed):
    waiting_chat = service.turn(indexed, "spend", None, {}, EMBED)
    with pytest.raises(AgentError):
        service.step(indexed, waiting_chat["token"], vector=NEAR_GYM)
    waiting_embed = service.step(
        indexed, waiting_chat["token"], reply=reply(chart="kpi", merchant="workout")
    )
    assert waiting_embed["request"]["kind"] == "embed"
    with pytest.raises(AgentError) as caught:
        service.step(indexed, waiting_embed["token"], reply=BAR)
    assert caught.value.code == "unexpected_step"


# --- what the token holds -------------------------------------------------------------------


def test_the_token_holds_no_chart_data(alice):
    token = converse(alice, "spend by category", [BAR])[-1]["token"]
    state = state_of(alice, token)
    assert state["spec"]["chart"] == "bar" and state["outcome"] == "preview"
    assert "result" not in json.dumps(state)


def test_the_token_stays_small_over_a_conversation(alice):
    token = None
    for message, answer in [("spend by category", BAR), ("weekly line", LINE), ("as bars", BAR)]:
        token = converse(alice, message, [answer], token=token)[-1]["token"]
    assert len(token) < 8192


def test_every_node_runs_on_the_requests_thread(alice, monkeypatch):
    threads = set()
    real = compiler.run_queries

    def recording(*args, **kwargs):
        threads.add(threading.get_ident())
        return real(*args, **kwargs)

    monkeypatch.setattr(compiler, "run_queries", recording)
    converse(alice, "spend by category", [BAR])
    assert threads == {threading.get_ident()}


def test_the_log_names_why_a_turn_failed(alice, settings, caplog):
    settings.AGENT_MAX_REPAIRS = 0
    with caplog.at_level("INFO", logger="ai.agent.service"):
        converse(alice, "spend", [BROKEN])
    assert "result=failed code=no_valid_panel" in caplog.text

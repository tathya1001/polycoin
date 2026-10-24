import base64
from dataclasses import dataclass
from typing import TypedDict

import pytest
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from ai.agent.errors import AgentError
from ai.agent.sealed import SealedSaver, seal, unseal
from transactions.tests import make_user

pytestmark = pytest.mark.django_db

VERSION = "g1"
NOW = 1_800_000_000.0


class State(TypedDict, total=False):
    count: int
    reply: str


def _count(state):
    return {"count": state.get("count", 0) + 1}


def _ask(state):
    return {"reply": interrupt({"kind": "chat"})}


def _graph(saver):
    builder = StateGraph(State)
    builder.add_node("count", _count)
    builder.add_node("ask", _ask)
    builder.add_edge(START, "count")
    builder.add_edge("count", "ask")
    builder.add_edge("ask", END)
    return builder.compile(checkpointer=saver)


def run(saver, value):
    config = {"configurable": {"thread_id": saver.thread_id}}
    chunks = list(_graph(saver).stream(value, config, durability="exit"))
    return chunks, _graph(saver).get_state(config)


@pytest.fixture
def alice():
    return make_user("alice@example.com")


@pytest.fixture
def bob():
    return make_user("bob@example.com")


def interrupted(user):
    """A token for a graph stopped at its interrupt."""
    saver = SealedSaver("thread-1")
    run(saver, {"count": 0})
    return seal(user, saver, VERSION, now=NOW)


# --- the saver ------------------------------------------------------------------------


def test_a_graph_resumes_from_a_saver_rebuilt_from_bytes():
    saver = SealedSaver("t")
    chunks, state = run(saver, {"count": 0})
    assert "__interrupt__" in chunks[-1] and state.next == ("ask",)

    again = SealedSaver.load("t", saver.dump())
    chunks, state = run(again, Command(resume="hello"))
    assert state.values == {"count": 1, "reply": "hello"} and state.next == ()


def test_new_input_starts_a_new_run_on_the_same_thread():
    saver = SealedSaver("t")
    run(saver, {"count": 0})
    run(saver, Command(resume="first"))
    _, state = run(SealedSaver.load("t", saver.dump()), {"count": 10})
    assert state.values["count"] == 11 and state.next == ("ask",)


def test_only_the_latest_checkpoint_is_kept():
    saver = SealedSaver("t")
    run(saver, {"count": 0})
    latest = saver.get_tuple({"configurable": {"thread_id": "t"}})
    assert len(list(saver.list(None))) == 1
    old = {"configurable": {"thread_id": "t", "checkpoint_ns": "", "checkpoint_id": "older"}}
    assert saver.get_tuple(old) is None
    assert saver.get_tuple({"configurable": {"thread_id": "other"}}) is None
    assert latest.pending_writes  # the interrupt


def test_writes_come_back_in_the_order_a_run_applies_them():
    saver = SealedSaver("t")
    run(saver, {"count": 0})
    config = saver.get_tuple({"configurable": {"thread_id": "t"}}).config
    saver.put_writes(config, [("reply", "b")], "task-b", task_path="2")
    saver.put_writes(config, [("reply", "a")], "task-a", task_path="1")
    writes = SealedSaver.load("t", saver.dump()).get_tuple(config).pending_writes
    ours = [value for task, _, value in writes if task.startswith("task-")]
    assert ours == ["a", "b"]


def test_delete_thread_empties_the_saver():
    saver = SealedSaver("t")
    run(saver, {"count": 0})
    saver.delete_thread("t")
    assert saver.get_tuple({"configurable": {"thread_id": "t"}}) is None
    with pytest.raises(ValueError):
        saver.dump()


def test_bytes_that_are_not_an_agent_state_are_refused():
    other = SealedSaver("t").serde.dumps_typed({"something": "else"})[1]
    with pytest.raises(ValueError):
        SealedSaver.load("t", other)


@dataclass
class Unlisted:
    value: int


def test_loading_never_rebuilds_an_unlisted_type():
    saver = SealedSaver("t")
    run(saver, {"count": 0})
    config = saver.get_tuple({"configurable": {"thread_id": "t"}}).config
    saver.put_writes(config, [("reply", Unlisted(1))], "task-x")
    writes = SealedSaver.load("t", saver.dump()).get_tuple(config).pending_writes
    (value,) = [value for task, _, value in writes if task == "task-x"]
    assert value == {"value": 1}


# --- the token -------------------------------------------------------------------------


def test_a_token_round_trips_for_its_user(alice):
    token = interrupted(alice)
    assert token.startswith(f"{VERSION}.")
    saver = unseal(alice, token, VERSION, now=NOW + 1)
    assert saver.thread_id == "thread-1"
    _, state = run(saver, Command(resume="hi"))
    assert state.values == {"count": 1, "reply": "hi"}


def test_the_token_hides_the_state(alice):
    saver = SealedSaver("thread-1")
    run(saver, {"count": 0})
    run(saver, Command(resume="Tastybites secret"))
    token = seal(alice, saver, VERSION, now=NOW)
    raw = base64.urlsafe_b64decode(token.split(".", 1)[1] + "==")
    assert b"Tastybites" not in raw and b"thread-1" not in raw


def test_another_user_cannot_use_the_token(alice, bob):
    with pytest.raises(AgentError) as caught:
        unseal(bob, interrupted(alice), VERSION, now=NOW)
    assert caught.value.code == "token_invalid"


@pytest.mark.parametrize("position", [len(VERSION) + 5, -3])
def test_a_changed_token_is_refused(alice, position):
    token = interrupted(alice)
    flipped = "A" if token[position] != "A" else "B"
    with pytest.raises(AgentError) as caught:
        unseal(alice, token[:position] + flipped + token[position + 1 :], VERSION, now=NOW)
    assert caught.value.code == "token_invalid"


@pytest.mark.parametrize(
    "token", ["", "no-dot", f"{VERSION}.", f"{VERSION}.!!!", f"{VERSION}.AAAA"]
)
def test_garbage_is_refused(alice, token):
    with pytest.raises(AgentError) as caught:
        unseal(alice, token, VERSION, now=NOW)
    assert caught.value.code == "token_invalid"


def test_a_token_that_is_not_text_is_refused(alice):
    with pytest.raises(AgentError):
        unseal(alice, None, VERSION)


def test_a_token_expires(alice, settings):
    token = interrupted(alice)
    unseal(alice, token, VERSION, now=NOW + settings.AGENT_TOKEN_TTL)  # still fine at the edge
    with pytest.raises(AgentError) as caught:
        unseal(alice, token, VERSION, now=NOW + settings.AGENT_TOKEN_TTL + 1)
    assert caught.value.code == "token_expired"


def test_a_token_from_another_graph_version_has_expired(alice):
    with pytest.raises(AgentError) as caught:
        unseal(alice, interrupted(alice), "g2", now=NOW)
    assert caught.value.code == "token_expired"


def test_relabelling_the_version_does_not_help(alice):
    token = interrupted(alice).replace(f"{VERSION}.", "g2.", 1)
    with pytest.raises(AgentError) as caught:
        unseal(alice, token, "g2", now=NOW)
    assert caught.value.code == "token_invalid"


def test_a_token_is_size_capped_both_ways(alice, settings):
    token = interrupted(alice)
    settings.AGENT_MAX_TOKEN_BYTES = len(token) - 1
    with pytest.raises(AgentError) as caught:
        unseal(alice, token, VERSION, now=NOW)
    assert caught.value.code == "token_invalid"  # refused before any decryption
    with pytest.raises(AgentError) as caught:
        interrupted(alice)
    assert caught.value.code == "state_too_large"


def test_a_small_graphs_token_is_small(alice):
    assert len(interrupted(alice)) < 2000


def test_a_graph_version_cannot_hold_the_separator(alice):
    saver = SealedSaver("thread-1")
    run(saver, {"count": 0})
    with pytest.raises(ValueError):
        seal(alice, saver, "agent.2")

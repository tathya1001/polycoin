"""The panel builder's workflow: a fixed, bounded LangGraph graph.

    begin -> understand -> ground -> [meaning] -> compile -> preview -> END
                 ^                                  |          |
                 +------------ retry <--------------+----------+

This is an "agentic workflow", not a free tool-calling loop (ReAct). Small local models are
unreliable at choosing tools, and a fixed graph bounds what one request can cost: at most
AGENT_MAX_STEPS model round trips per turn and AGENT_MAX_REPAIRS repairs.

The server never calls a model. A node that needs one stops the graph with `interrupt()`; the
state goes to the browser in a sealed token, the browser asks the user's Ollama, and the reply
resumes the graph. Only plain data is kept in the state, so the token stays small: the prompt is
rebuilt from the state each time, and the user's categories come in, and the turn's outcome
(with the preview's chart data) goes out, through the runtime context.

The graph is streamed with "updates" only. Stream modes such as "custom" make LangGraph run
nodes on a thread pool, where Django would open a database connection per thread and never close
it; with "updates", each node runs on the request's own thread.
"""

from dataclasses import asdict
from typing import TypedDict

from django.conf import settings
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import interrupt

from insights.spec import SpecError

from .compile import Grounding, compile_intent, describe, ground, resolve_by_meaning, run_preview
from .context import AgentContext, merchant_by_meaning
from .errors import AgentError
from .schema import PanelIntent, parse_intent

# Part of every token's encryption context: raise it whenever the state's shape or the graph
# changes, and older tokens expire instead of resuming into a graph they don't fit.
GRAPH_VERSION = "agent-2"
RECURSION_LIMIT = 25  # LangGraph's own cap on steps in one run; the counters below stop first


class AgentState(TypedDict, total=False):
    # Given with each turn.
    message: str  # the user's latest message
    dashboard: dict  # the dashboard's validated {"filters", "parameters"}
    embed: dict | None  # the browser's embedding model {"model", "digest"}, if it has one
    # Counters.
    turns: int  # messages in this conversation
    steps: int  # model round trips in this turn
    repairs: int  # repairs in this turn
    # The panel the user has, which a follow-up changes. Set only when a preview succeeds.
    intent: dict | None
    spec: dict | None
    title: str | None
    # This turn's work.
    draft: dict | None  # the model's latest parsed intent
    grounding: dict | None
    candidate: dict | None  # a compiled panel waiting for its preview
    last_error: str | None  # why the last reply was refused, for the repair prompt
    outcome: str | None  # "preview", "not_a_panel" or "failed" once the turn is over
    merchants: dict  # merchant phrase -> match, so a follow-up skips the merchant scan


def _emit(runtime: Runtime[AgentContext], outcome: dict) -> None:
    """The turn's result, handed to the caller instead of being stored in the token."""
    runtime.context.outcome = outcome


def _next_step(state: AgentState) -> int:
    steps = state.get("steps", 0) + 1
    if steps > settings.AGENT_MAX_STEPS:
        raise AgentError("too_many_steps", "This took too many tries. Try a simpler request.")
    return steps


# --- nodes ------------------------------------------------------------------------------
# A node that calls interrupt() runs again from the top when the graph resumes, so everything
# before the interrupt must be free of side effects.


def begin(state: AgentState) -> dict:
    turns = state.get("turns", 0) + 1
    if turns > settings.AGENT_MAX_TURNS:
        raise AgentError("too_many_turns", "This conversation is long. Start a new one.")
    return {
        "turns": turns,
        "steps": 0,
        "repairs": 0,
        "draft": None,
        "grounding": None,
        "candidate": None,
        "last_error": None,
        "outcome": None,
    }


def prompt_kind(state: AgentState) -> str:
    """Which prompt the model gets: a repair after a refused reply, a refine when there is
    already a panel, otherwise a fresh request."""
    if state.get("last_error"):
        return "repair"
    return "refine" if state.get("intent") else "understand"


def understand(state: AgentState, runtime: Runtime[AgentContext]) -> dict:
    steps = _next_step(state)
    reply = interrupt({"kind": "chat", "prompt": prompt_kind(state)})
    try:
        intent = parse_intent(reply)
    except AgentError as problem:
        return {"steps": steps, "draft": None, "last_error": problem.detail}
    if intent.kind == "not_a_panel":
        _emit(runtime, {"kind": "not_a_panel", "reason": intent.reason or "That is not a chart."})
        return {"steps": steps, "last_error": None, "outcome": "not_a_panel"}
    return {"steps": steps, "draft": intent.model_dump(), "last_error": None}


def retry(state: AgentState, runtime: Runtime[AgentContext]) -> dict:
    """Another try for the model, or the end of the turn once the repairs are used up."""
    if state.get("repairs", 0) >= settings.AGENT_MAX_REPAIRS:
        _emit(
            runtime,
            {
                "kind": "failed",
                "code": "no_valid_panel",
                "detail": " ".join(
                    ["The model could not make this panel.", state.get("last_error") or ""]
                ).strip(),
            },
        )
        return {"outcome": "failed"}
    return {"repairs": state.get("repairs", 0) + 1}


def ground_words(state: AgentState, runtime: Runtime[AgentContext]) -> dict:
    cache = dict(state.get("merchants") or {})
    grounding = ground(PanelIntent(**state["draft"]), runtime.context, cache)
    return {"grounding": asdict(grounding), "merchants": cache}


def meaning(state: AgentState, runtime: Runtime[AgentContext]) -> dict:
    """A merchant no name matched: the browser embeds the phrase, the "Ask" index finds it."""
    steps = _next_step(state)
    grounding = Grounding(**state["grounding"])
    vector = interrupt({"kind": "embed", "text": grounding.pending_merchant})
    found = (
        merchant_by_meaning(runtime.context, grounding.pending_merchant, vector) if vector else None
    )
    cache = dict(state.get("merchants") or {})
    resolve_by_meaning(grounding, found, cache)
    return {"steps": steps, "grounding": asdict(grounding), "merchants": cache}


def compile_panel(state: AgentState, runtime: Runtime[AgentContext]) -> dict:
    try:
        compiled = compile_intent(
            PanelIntent(**state["draft"]),
            Grounding(**state["grounding"]),
            runtime.context,
            message=state["message"],
            dashboard_date=state["dashboard"]["filters"]["date"],
        )
    except SpecError as problem:
        return {"last_error": problem.detail}
    return {
        "candidate": {
            "spec": compiled.spec,
            "title": compiled.title,
            "notes": compiled.notes,
            "intent": compiled.intent.model_dump(),
        },
        "last_error": None,
    }


def preview(state: AgentState, runtime: Runtime[AgentContext]) -> dict:
    ctx, candidate = runtime.context, state["candidate"]
    shown = run_preview(
        ctx.user, candidate["spec"], state["dashboard"], ctx.today, candidate["notes"]
    )
    if shown.error is None:
        _emit(
            runtime,
            {
                "kind": "preview",
                "title": candidate["title"],
                "summary": describe(shown.spec),
                "config": shown.spec,
                "result": shown.result,
                "notes": shown.notes,
            },
        )
        return {
            "intent": candidate["intent"],
            "spec": shown.spec,
            "title": candidate["title"],
            "candidate": None,
            "outcome": "preview",
        }
    if shown.repairable:
        return {
            "candidate": None,
            "last_error": f"The panel could not be drawn: {shown.error['detail']}",
        }
    _emit(
        runtime,
        {"kind": "failed", **shown.error, "config": shown.spec, "title": candidate["title"]},
    )
    return {"candidate": None, "outcome": "failed"}


# --- edges ------------------------------------------------------------------------------


def after_understand(state: AgentState) -> str:
    if state.get("outcome"):
        return END
    return "retry" if state.get("last_error") else "ground"


def after_retry(state: AgentState) -> str:
    return END if state.get("outcome") else "understand"


def after_ground(state: AgentState) -> str:
    return "meaning" if state["grounding"]["pending_merchant"] else "compile"


def after_compile(state: AgentState) -> str:
    return "retry" if state.get("last_error") else "preview"


def after_preview(state: AgentState) -> str:
    return END if state.get("outcome") else "retry"


def build() -> StateGraph:
    graph = StateGraph(AgentState, context_schema=AgentContext)
    graph.add_node("begin", begin)
    graph.add_node("understand", understand)
    graph.add_node("retry", retry)
    graph.add_node("ground", ground_words)
    graph.add_node("meaning", meaning)
    graph.add_node("compile", compile_panel)
    graph.add_node("preview", preview)
    graph.add_edge(START, "begin")
    graph.add_edge("begin", "understand")
    graph.add_conditional_edges("understand", after_understand, ["retry", "ground", END])
    graph.add_conditional_edges("retry", after_retry, ["understand", END])
    graph.add_conditional_edges("ground", after_ground, ["meaning", "compile"])
    graph.add_edge("meaning", "compile")
    graph.add_conditional_edges("compile", after_compile, ["retry", "preview"])
    graph.add_conditional_edges("preview", after_preview, ["retry", END])
    return graph


# Built once. Each request compiles it (well under a millisecond) with its own SealedSaver,
# because the checkpointer holds that request's state and must never be shared.
BUILDER = build()

"""Runs the panel builder for one HTTP request: a turn (a new message) or a step (the model's
reply, relayed by the browser).

Each request rebuilds the state from the sealed token, runs the graph until it needs the model
again or finishes, and seals the state into a new token. The response is either what the browser
should ask its Ollama next (`needs_model`) or the turn's outcome (`done`).
"""

import logging
import time
import uuid

from langgraph.errors import GraphRecursionError
from langgraph.types import Command

from insights.spec import SpecError, validate_filters, validate_parameters

from ..rag.profiles import profile_for
from .context import build_context
from .errors import AgentError
from .graph import BUILDER, GRAPH_VERSION, RECURSION_LIMIT
from .prompts import PROMPT_VERSION, build_messages, chat_request
from .schema import PanelIntent
from .sealed import SealedSaver, seal, unseal

logger = logging.getLogger(__name__)

PROGRESS = {
    "understand": "Reading your request",
    "refine": "Changing the panel",
    "repair": "Fixing the panel",
    "embed": "Looking up the merchant",
}


def clean_dashboard(raw) -> dict:
    """The dashboard the panel will sit on: its filter bar and parameters, validated."""
    raw = raw if isinstance(raw, dict) else {}
    try:
        return {
            "filters": validate_filters(raw.get("filters")),
            "parameters": validate_parameters(raw.get("parameters")),
        }
    except SpecError as problem:
        raise AgentError("invalid_filters", problem.detail) from None


def _config(saver: SealedSaver) -> dict:
    return {"configurable": {"thread_id": saver.thread_id}, "recursion_limit": RECURSION_LIMIT}


def _pending(snapshot) -> dict | None:
    """The interrupt the graph is waiting on: {"kind": "chat", ...} or {"kind": "embed", ...}."""
    return snapshot.interrupts[0].value if snapshot.interrupts else None


def _model_request(state: dict, waiting: dict, ctx) -> tuple[dict, dict]:
    """(what the browser sends to its Ollama, the progress line it shows)."""
    if waiting["kind"] == "embed":
        model = state["embed"]["model"]
        text = profile_for(model).query_prefix + waiting["text"]
        return {"kind": "embed", "model": model, "text": text}, {
            "label": PROGRESS["embed"],
            "attempt": 1,
        }
    kind = waiting["prompt"]
    # A refine shows the user's current panel. A repair shows only what the model itself last
    # replied (none when that reply did not parse), never the current panel as if it were the
    # model's own reply.
    shown = {"refine": state.get("intent"), "repair": state.get("draft")}.get(kind)
    messages = build_messages(
        kind,
        message=state["message"],
        category_names=ctx.categories.names,
        source_names=ctx.sources.names,
        today=ctx.today,
        intent=PanelIntent(**shown) if shown else None,
        error=state.get("last_error"),
    )
    progress = {"label": PROGRESS[kind], "attempt": state.get("repairs", 0) + 1}
    return chat_request(messages), progress


def _run(user, saver: SealedSaver, value, ctx, action: str) -> dict:
    started = time.perf_counter()
    graph = BUILDER.compile(checkpointer=saver)
    ctx.outcome = None
    try:
        # "updates" only, so every node runs on this thread (see graph.py).
        for _ in graph.stream(
            value, _config(saver), context=ctx, stream_mode="updates", durability="exit"
        ):
            pass
    except GraphRecursionError:
        raise AgentError(
            "too_many_steps", "This took too many tries. Try a simpler request."
        ) from None

    snapshot = graph.get_state(_config(saver))
    state, waiting, outcome = snapshot.values, _pending(snapshot), ctx.outcome
    token = seal(user, saver, GRAPH_VERSION)
    if waiting:
        request, progress = _model_request(state, waiting, ctx)
        response = {
            "status": "needs_model",
            "token": token,
            "progress": progress,
            "request": request,
        }
        result = request["kind"]
    else:
        response = {"status": "done", "token": token, "outcome": outcome}
        result = (outcome or {}).get("kind", "none")
    # Counts, codes and timings only: never the message, the reply or the panel.
    logger.info(
        "agent %s: prompt=%s result=%s code=%s turn=%d step=%d repairs=%d notes=%d token=%d "
        "ms=%.0f",
        action,
        PROMPT_VERSION,
        result,
        (outcome or {}).get("code", "-") if not waiting else "-",
        state.get("turns", 0),
        state.get("steps", 0),
        state.get("repairs", 0),
        len((outcome or {}).get("notes", ())),
        len(token),
        (time.perf_counter() - started) * 1000,
    )
    return response


def turn(user, message: str, token: str | None, dashboard, embed: dict | None) -> dict:
    """A new message: the first of a conversation (no token), or a follow-up on its panel."""
    dashboard = clean_dashboard(dashboard)
    saver = unseal(user, token, GRAPH_VERSION) if token else SealedSaver(uuid.uuid4().hex)
    ctx = build_context(user, embed=embed)
    value = {"message": message, "dashboard": dashboard, "embed": ctx.embed}
    return _run(user, saver, value, ctx, "turn")


def step(user, token: str, reply: str | None = None, vector=None, skip: bool = False) -> dict:
    """The model's answer to the last `needs_model`: a chat `reply`, an embedding `vector`, or
    `skip` when the browser has no embedding model."""
    saver = unseal(user, token, GRAPH_VERSION)
    snapshot = BUILDER.compile(checkpointer=saver).get_state(_config(saver))
    waiting = _pending(snapshot)
    if waiting is None:
        raise AgentError("unexpected_step", "Nothing is waiting for the model. Send a message.")
    if waiting["kind"] == "chat":
        if reply is None:
            raise AgentError("unexpected_step", "The model's reply was expected.")
        value = reply
    else:
        if reply is not None:
            raise AgentError("unexpected_step", "An embedding was expected.")
        # An empty list, not None: LangGraph cannot resume with None.
        value = [] if skip else vector
    ctx = build_context(user, embed=snapshot.values.get("embed"))
    return _run(user, saver, Command(resume=value), ctx, "step")

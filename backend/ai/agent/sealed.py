"""Agent state with no server storage: a LangGraph checkpointer whose only copy of the state
goes back to the browser, encrypted with the user's own key.

`SealedSaver` is a LangGraph checkpointer (the documented `BaseCheckpointSaver` extension
point) for exactly one thread. It keeps only the latest checkpoint and that checkpoint's pending
writes, which is all a graph needs to resume after an interrupt. The graph runs with
durability="exit", so it is written once, when the run stops.

`seal` turns the saver into a token: msgpack from LangGraph's own serialiser, in strict mode and
without pickle, encrypted with UserCipher. The encryption context names the user and the graph
version, so a token cannot be replayed by another user, or into a graph whose state has changed
shape. The token carries its expiry inside the ciphertext, so it cannot be extended.

A token can be sent again until it expires. That only rewinds the user's own conversation (a new
one is always free to start), so it grants nothing; the request throttle bounds the work.
"""

import base64
import binascii
import json
import time
from collections.abc import Iterator, Sequence
from typing import Any

from cryptography.exceptions import InvalidTag
from django.conf import settings
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import (
    WRITES_IDX_MAP,
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
    get_checkpoint_id,
    get_checkpoint_metadata,
    writes_sort_key,
)
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from vault.services import UserCipher

from .errors import AgentError

TOKEN_VERSION = 1


def _context(graph_version: str) -> str:
    return f"agent.state:{graph_version}"


class SealedSaver(BaseCheckpointSaver):
    """A checkpointer for one thread that keeps only the latest checkpoint and its writes."""

    def __init__(self, thread_id: str):
        # No pickle: a forged state must never be able to run code when it is loaded.
        super().__init__(serde=JsonPlusSerializer(pickle_fallback=False))
        self.thread_id = thread_id
        # Changed in place, never reassigned: a compiled graph works on a shallow copy of its
        # checkpointer (with_allowlist), and every copy must see the same state.
        self._store: dict = {
            "saved": None,  # {"ns", "checkpoint", "metadata", "parent"}
            # (checkpoint id, task id, index) -> (task id, channel, value, task path)
            "writes": {},
        }

    # --- the checkpointer interface ---------------------------------------------------

    def _config(self, checkpoint_id: str) -> RunnableConfig:
        return {
            "configurable": {
                "thread_id": self.thread_id,
                "checkpoint_ns": self._store["saved"]["ns"],
                "checkpoint_id": checkpoint_id,
            }
        }

    def get_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        saved = self._store["saved"]
        if saved is None or config["configurable"].get("thread_id") != self.thread_id:
            return None
        if config["configurable"].get("checkpoint_ns", "") != saved["ns"]:
            return None
        checkpoint_id = saved["checkpoint"]["id"]
        wanted = get_checkpoint_id(config)
        if wanted and wanted != checkpoint_id:
            return None  # only the latest checkpoint is kept
        writes = self._ordered_writes(checkpoint_id)
        return CheckpointTuple(
            config=self._config(checkpoint_id),
            checkpoint=saved["checkpoint"],
            metadata=saved["metadata"],
            parent_config=self._config(saved["parent"]) if saved["parent"] else None,
            pending_writes=[(task_id, channel, value) for task_id, channel, value, _ in writes],
        )

    def _ordered_writes(self, checkpoint_id: str) -> list[tuple]:
        """The checkpoint's writes in the order a live run applies them."""
        mine = [
            (key, write) for key, write in self._store["writes"].items() if key[0] == checkpoint_id
        ]
        mine.sort(key=lambda item: writes_sort_key(item[1][3], item[0][1], item[0][2]))
        return [write for _, write in mine]

    def list(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> Iterator[CheckpointTuple]:
        found = self.get_tuple(config or {"configurable": {"thread_id": self.thread_id}})
        if found and not before and limit != 0:
            if not filter or all(found.metadata.get(k) == v for k, v in filter.items()):
                yield found

    def put(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        self._store["saved"] = {
            "ns": config["configurable"].get("checkpoint_ns", ""),
            "checkpoint": checkpoint.copy(),
            "metadata": get_checkpoint_metadata(config, metadata),
            "parent": config["configurable"].get("checkpoint_id"),
        }
        # Writes belong to one checkpoint; those of older checkpoints are never read again.
        writes = self._store["writes"]
        for key in [key for key in writes if key[0] != checkpoint["id"]]:
            del writes[key]
        return self._config(checkpoint["id"])

    def put_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        checkpoint_id = config["configurable"]["checkpoint_id"]
        stored = self._store["writes"]
        for index, (channel, value) in enumerate(writes):
            key = (checkpoint_id, task_id, WRITES_IDX_MAP.get(channel, index))
            if key[2] >= 0 and key in stored:
                continue  # as InMemorySaver: a special write (an error, an interrupt) is kept once
            stored[key] = (task_id, channel, value, task_path)

    def delete_thread(self, thread_id: str) -> None:
        if thread_id == self.thread_id:
            self._store["saved"] = None
            self._store["writes"].clear()

    # --- to and from bytes -----------------------------------------------------------

    def dump(self) -> bytes:
        """The latest checkpoint and its writes as msgpack."""
        saved = self._store["saved"]
        if saved is None:
            raise ValueError("Nothing to seal: the graph has not run.")
        checkpoint_id = saved["checkpoint"]["id"]
        writes = [
            [[key[1], key[2]], list(write)]
            for key, write in self._store["writes"].items()
            if key[0] == checkpoint_id
        ]
        kind, data = self.serde.dumps_typed({**saved, "writes": writes})
        if kind != "msgpack":
            raise ValueError("The agent state must be plain data.")
        return data

    @classmethod
    def load(cls, thread_id: str, data: bytes) -> "SealedSaver":
        saver = cls(thread_id)
        payload = saver.serde.loads_typed(("msgpack", data))
        if not isinstance(payload, dict) or set(payload) != {
            "ns", "checkpoint", "metadata", "parent", "writes",
        }:  # fmt: skip
            raise ValueError("Not an agent state.")
        writes = payload.pop("writes")
        saver._store["saved"] = payload
        checkpoint_id = payload["checkpoint"]["id"]
        for (task_id, index), (task, channel, value, task_path) in writes:
            saver._store["writes"][(checkpoint_id, task_id, index)] = (
                task, channel, value, task_path,
            )  # fmt: skip
        return saver


# --- the token ------------------------------------------------------------------------


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _b64decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def seal(user, saver: SealedSaver, graph_version: str, now: float | None = None) -> str:
    """`<graph version>.<base64url ciphertext>`. The version is outside the ciphertext only so a
    token from an older graph can be told apart from a damaged one; it is also inside the
    encryption context, so changing it breaks the token."""
    if "." in graph_version:
        raise ValueError("The graph version must not contain a dot: it separates the token.")
    now = time.time() if now is None else now
    envelope = {
        "v": TOKEN_VERSION,
        "exp": int(now) + settings.AGENT_TOKEN_TTL,
        "tid": saver.thread_id,
        "cp": _b64encode(saver.dump()),
    }
    blob = UserCipher(user).encrypt(json.dumps(envelope).encode(), _context(graph_version))
    token = f"{graph_version}.{_b64encode(blob)}"
    if len(token) > settings.AGENT_MAX_TOKEN_BYTES:
        raise AgentError("state_too_large", "This conversation is too long. Start a new one.")
    return token


def unseal(user, token: str, graph_version: str, now: float | None = None) -> SealedSaver:
    """The saver inside a token. Raises AgentError token_invalid or token_expired."""
    invalid = AgentError("token_invalid", "This conversation can't be continued. Start a new one.")
    expired = AgentError("token_expired", "This conversation has expired. Start a new one.")
    if not isinstance(token, str) or len(token) > settings.AGENT_MAX_TOKEN_BYTES:
        raise invalid
    version, dot, body = token.partition(".")
    if not dot:
        raise invalid
    if version != graph_version:
        raise expired  # made by another version of the graph, e.g. before a deploy
    try:
        plain = UserCipher(user).decrypt(_b64decode(body), _context(graph_version))
        envelope = json.loads(plain)
        if envelope["v"] != TOKEN_VERSION or not isinstance(envelope["exp"], int):
            raise invalid
        if envelope["exp"] < (time.time() if now is None else now):
            raise expired
        return SealedSaver.load(str(envelope["tid"]), _b64decode(envelope["cp"]))
    except AgentError:
        raise
    except (InvalidTag, ValueError, KeyError, TypeError, binascii.Error):
        raise invalid from None

import os
import re
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path

from django.conf import settings as django_settings

REQUIREMENTS = Path(__file__).resolve().parent.parent / "requirements.txt"


@dataclass
class Unlisted:
    """A type LangGraph can encode, but which is not on its safe list."""

    value: int


def test_the_agent_throttle_scope_has_a_rate(settings):
    assert settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]["agent"] == "300/hour"


def test_strict_msgpack_is_forced_on():
    from langgraph.checkpoint.serde import _msgpack

    assert os.environ["LANGGRAPH_STRICT_MSGPACK"] == "true"
    assert _msgpack.STRICT_MSGPACK_ENABLED is True


def test_strict_serialiser_does_not_rebuild_unknown_types():
    from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

    serde = JsonPlusSerializer(pickle_fallback=False)
    loaded = serde.loads_typed(serde.dumps_typed({"payload": Unlisted(1)}))
    # The fields come back as plain data; the class is never called.
    assert loaded == {"payload": {"value": 1}}


def test_strict_serialiser_keeps_json_primitives():
    from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

    state = {"message": "spend by category", "notes": ["a"], "repairs": 1, "spec": None}
    serde = JsonPlusSerializer(pickle_fallback=False)
    assert serde.loads_typed(serde.dumps_typed(state)) == state


def test_agent_limits_are_positive_and_bounded():
    s = django_settings
    assert isinstance(s.AGENT_ENABLED, bool)
    for name in (
        "AGENT_TOKEN_TTL",
        "AGENT_MAX_TOKEN_BYTES",
        "AGENT_MAX_TURNS",
        "AGENT_MAX_STEPS",
        "AGENT_MERCHANT_SCAN",
        "AGENT_NUM_CTX",
        "AGENT_NUM_PREDICT",
    ):
        assert getattr(s, name) > 0, name
    assert s.AGENT_MAX_REPAIRS >= 0
    # Each repair is one more model round trip, so the repairs must fit in one turn's steps.
    assert s.AGENT_MAX_REPAIRS < s.AGENT_MAX_STEPS
    assert s.AGENT_NUM_PREDICT < s.AGENT_NUM_CTX


def test_installed_agent_packages_match_the_pins():
    text = REQUIREMENTS.read_text()
    for package in ("langgraph", "langgraph-checkpoint", "pydantic", "langchain-core"):
        match = re.search(rf"^{re.escape(package)}==(\S+)$", text, re.MULTILINE)
        assert match, f"{package} is not pinned exactly"
        assert version(package) == match.group(1), package

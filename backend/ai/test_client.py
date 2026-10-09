"""OllamaClient tests. `httpx.request` is replaced, so nothing here touches the network."""

import httpx
import pytest

from ai import client as client_module
from ai.client import AIError, OllamaClient

SECRET = "SECRET-NARRATION-9f3a"  # stands in for a real bank narration

BASE = "http://ollama.test"


def respond(monkeypatch, handler):
    """Route every httpx.request call through `handler(method, url, **kwargs)`."""
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append({"method": method, "url": url, **kwargs})
        return handler(method, url, **kwargs)

    monkeypatch.setattr(httpx, "request", fake_request)
    return calls


def always(status, payload=None):
    return lambda *args, **kwargs: httpx.Response(status, json=payload if payload is not None else {})


@pytest.fixture
def ollama():
    return OllamaClient(base_url=BASE + "/", timeout=5)


# --- list_models --------------------------------------------------------------

TAGS = {
    "models": [
        {
            "name": "nomic-embed-text:latest",
            "capabilities": ["embedding"],
            "details": {"embedding_length": 768},
        },
        {"name": "llama3.2:latest", "capabilities": ["completion", "tools"], "details": {}},
        {"name": "tinyllama:latest", "capabilities": ["completion"], "details": {}},
    ]
}


def test_list_models_keeps_only_embedding_capable_models(monkeypatch, ollama):
    calls = respond(monkeypatch, always(200, TAGS))

    assert ollama.list_models() == [{"name": "nomic-embed-text:latest", "dimension": 768}]
    assert calls[0]["method"] == "GET"
    assert calls[0]["url"] == f"{BASE}/api/tags"  # trailing slash on base_url is stripped
    assert calls[0]["timeout"] == 5


def test_list_models_falls_back_to_the_name_when_capabilities_are_missing(monkeypatch, ollama):
    old_style = {"models": [{"name": "nomic-embed-text:latest"}, {"name": "llama3:latest"}]}
    respond(monkeypatch, always(200, old_style))

    assert ollama.list_models() == [{"name": "nomic-embed-text:latest", "dimension": None}]


def test_an_embedder_listed_after_other_models_is_still_found(monkeypatch, ollama):
    chat_first = {"models": [TAGS["models"][1], TAGS["models"][2], TAGS["models"][0]]}
    respond(monkeypatch, always(200, chat_first))

    assert [m["name"] for m in ollama.list_models()] == ["nomic-embed-text:latest"]


def test_no_embedding_model_installed_is_a_typed_error_with_instructions(monkeypatch, ollama):
    respond(monkeypatch, always(200, {"models": TAGS["models"][1:]}))

    with pytest.raises(AIError) as raised:
        ollama.list_models()

    assert raised.value.code == "no_embedding_models"
    assert "ollama pull" in raised.value.detail


def test_list_models_with_a_non_200_answer_is_unreachable(monkeypatch, ollama):
    respond(monkeypatch, always(500))

    with pytest.raises(AIError) as raised:
        ollama.list_models()

    assert raised.value.code == "ollama_unreachable"


@pytest.mark.parametrize(
    "error", [httpx.ConnectError("refused"), httpx.ReadTimeout("slow")]
)
def test_transport_failures_become_ollama_unreachable(monkeypatch, ollama, error):
    def boom(*args, **kwargs):
        raise error

    respond(monkeypatch, boom)

    with pytest.raises(AIError) as raised:
        ollama.embed("m", ["a"])

    assert raised.value.code == "ollama_unreachable"
    assert raised.value.__cause__ is None
    assert raised.value.__suppress_context__ is True  # `from None`: hidden from tracebacks


# --- embed --------------------------------------------------------------------


def echo_lengths(method, url, **kwargs):
    """Answers each input with a one-number vector holding the input's length."""
    return httpx.Response(200, json={"embeddings": [[float(len(t))] for t in kwargs["json"]["input"]]})


def test_embed_sends_model_and_batch_and_returns_vectors_in_order(monkeypatch, ollama):
    calls = respond(monkeypatch, echo_lengths)

    assert ollama.embed("nomic", ["a", "bb"]) == [[1.0], [2.0]]
    assert calls[0]["method"] == "POST"
    assert calls[0]["url"] == f"{BASE}/api/embed"
    assert calls[0]["json"] == {"model": "nomic", "input": ["a", "bb"]}


def test_embed_splits_into_batches_and_keeps_order(monkeypatch, ollama):
    monkeypatch.setattr(client_module, "BATCH_SIZE", 2)
    calls = respond(monkeypatch, echo_lengths)
    texts = ["a", "bb", "ccc", "dddd", "eeeee"]

    vectors = ollama.embed("m", texts)

    assert [len(call["json"]["input"]) for call in calls] == [2, 2, 1]
    assert vectors == [[float(len(t))] for t in texts]


def test_embed_with_no_texts_makes_no_request(monkeypatch, ollama):
    calls = respond(monkeypatch, echo_lengths)

    assert ollama.embed("m", []) == []
    assert calls == []


def test_embed_unknown_model_is_model_not_found(monkeypatch, ollama):
    respond(monkeypatch, always(404, {"error": 'model "x" not found, try pulling it first'}))

    with pytest.raises(AIError) as raised:
        ollama.embed("x", ["a"])

    assert raised.value.code == "model_not_found"


# Each of these makes Ollama misbehave in a different way, with the secret narration in the
# request. None of the resulting errors may repeat it.
def wrong_count(*args, **kwargs):
    return httpx.Response(200, json={"embeddings": [[1.0]]})


def missing_key(*args, **kwargs):
    return httpx.Response(200, json={})


@pytest.mark.parametrize(
    "handler, code",
    [
        (always(500), "embedding_failed"),
        (wrong_count, "embedding_failed"),
        (missing_key, "embedding_failed"),
    ],
)
def test_bad_ollama_answers_are_typed_and_never_echo_the_input(monkeypatch, ollama, handler, code):
    respond(monkeypatch, handler)

    with pytest.raises(AIError) as raised:
        ollama.embed("m", [SECRET, SECRET + "-2"])

    assert raised.value.code == code
    assert SECRET not in str(raised.value)
    assert SECRET not in raised.value.detail


def test_vectors_of_different_sizes_are_rejected_not_compared(monkeypatch, ollama):
    monkeypatch.setattr(client_module, "BATCH_SIZE", 1)
    answers = iter([[[1.0, 2.0]], [[1.0, 2.0, 3.0]]])  # second batch has another dimension
    respond(monkeypatch, lambda *a, **k: httpx.Response(200, json={"embeddings": next(answers)}))

    with pytest.raises(AIError) as raised:
        ollama.embed("m", [SECRET, SECRET + "-2"])

    assert raised.value.code == "dimension_mismatch"
    assert SECRET not in str(raised.value)


def test_unreachable_error_does_not_echo_the_input(monkeypatch, ollama):
    def boom(*args, **kwargs):
        raise httpx.ConnectError(f"failed sending {SECRET}")

    respond(monkeypatch, boom)

    with pytest.raises(AIError) as raised:
        ollama.embed("m", [SECRET])

    assert SECRET not in str(raised.value)
    # httpx's own message may contain request details; `from None` keeps it out of any
    # traceback or log line that formats this error.
    assert raised.value.__cause__ is None
    assert raised.value.__suppress_context__ is True


def test_defaults_come_from_settings(settings):
    settings.OLLAMA_BASE_URL = "http://configured:11434/"
    settings.OLLAMA_TIMEOUT = 12.5

    built = OllamaClient()

    assert built.base_url == "http://configured:11434"
    assert built.timeout == 12.5

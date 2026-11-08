"""Opt-in answer quality with a real chat model: the production prompt, sent to a local Ollama.

Dev machine only, fictional data only; never in CI or production. It reports rather than gates,
because answer quality depends on the user's own model:

    docker compose exec -e RAG_LLM_EVAL=1 backend pytest ai/test_rag_generation_eval.py -s

RAG_LLM_MODEL picks the chat model (default llama3.2:latest); OLLAMA_URL its address;
RAG_LLM_FORMAT=json asks for structured answers, as the Ask page setting does;
RAG_LLM_SAMPLE answers only an even sample of that many questions (default: all of them);
RAG_LLM_RECORD=<label> saves the run for the evaluation report; RAG_LLM_REPLAY=<label> re-scores a
saved run's answers (same questions, same order) without calling the model, so its timings are 0.
The production chat options are sent with a fixed seed, so a rerun gives the same answers. The
checks are in ai/eval/answers.py.
"""

import json
import os
import urllib.request

import pytest

from ai.eval import answers, results
from ai.eval.embed import DEFAULT_URL, TIMEOUT, ipv4_url
from ai.rag.answer import ANSWER_SCHEMA, chat_options, prompt_version

pytestmark = pytest.mark.skipif(
    not os.environ.get("RAG_LLM_EVAL"), reason="set RAG_LLM_EVAL=1 (needs a local Ollama)"
)

MODEL = os.environ.get("RAG_LLM_MODEL", "llama3.2:latest")
FORMAT = os.environ.get("RAG_LLM_FORMAT", "text")  # "json": structured answers, as the setting
SEED = 2026


def chat(messages: list[dict]) -> tuple[str, list[int] | None]:
    base = ipv4_url(os.environ.get("OLLAMA_URL", DEFAULT_URL))
    body = {
        "model": MODEL,
        "messages": messages,
        "stream": False,
        "options": {**chat_options(), "seed": SEED},
    }
    if FORMAT == "json":
        body["format"] = ANSWER_SCHEMA
    request = urllib.request.Request(
        f"{base}/api/chat", json.dumps(body).encode(), {"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT * 3) as response:
        content = json.load(response)["message"]["content"]
    if FORMAT != "json":
        return content, None
    # As the page does (lib/rag.ts readStructured): an answer of the wrong shape counts as empty.
    try:
        reply = json.loads(content)
        answer, citations = reply["answer"], reply["citations"]
        if not isinstance(answer, str) or not all(isinstance(n, int) for n in citations):
            raise ValueError
    except (ValueError, KeyError, TypeError):
        return "", []
    return answer, citations


def replay(label: str):
    """A saved run's answers in the order they were asked, to re-score them without the model."""
    stored = iter(answers.current_records(results.load("answers", label)["results"]))

    def chat(messages: list[dict]) -> tuple[str, list[int] | None]:
        record = next(stored)
        listed = [n for n in record["cited"] if FORMAT == "json"] or None
        return record["answer"], listed

    return chat


def test_answer_quality_report():
    sample = int(os.environ["RAG_LLM_SAMPLE"]) if os.environ.get("RAG_LLM_SAMPLE") else None
    source = replay(os.environ["RAG_LLM_REPLAY"]) if os.environ.get("RAG_LLM_REPLAY") else chat
    found = answers.run(source, sample, answer_format=FORMAT)
    numbers = answers.summary(found)
    print(f"\nAnswer quality with {MODEL}, prompt {prompt_version(FORMAT)}:")
    for name, value in numbers.items():
        print(f"  {name:28} {value}")
    if os.environ.get("RAG_LLM_RECORD"):
        path = results.save(
            "answers",
            os.environ["RAG_LLM_RECORD"],
            {
                "meta": results.metadata(
                    chat_model=MODEL,
                    prompt_version=prompt_version(FORMAT),
                    seed=SEED,
                    answer_format=FORMAT,
                ),  # fmt: skip
                "headline": {"chat model": MODEL, "format": FORMAT, **numbers},
                "results": answers.as_records(found),
            },
        )
        print(f"  saved {path.name}")
    assert numbers["answers"] > 0

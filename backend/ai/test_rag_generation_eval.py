"""Opt-in answer quality with a real chat model: the production prompt, sent to a local Ollama.

Dev machine only, fictional data only; never in CI or production. It reports rather than gates,
because answer quality depends on the user's own model:

    docker compose exec -e RAG_LLM_EVAL=1 backend pytest ai/test_rag_generation_eval.py -s

RAG_LLM_MODEL picks the chat model (default llama3.2:latest); OLLAMA_URL its address.

Measured:
- answers that cite: share of answers with at least one valid [n];
- citation precision: share of valid citations that point at a relevant row;
- invalid references: share of citations to a number that isn't in the prompt;
- "not found" on irrelevant sources: given only unrelated rows, does the model say so?
"""

import json
import os
import re
import urllib.request
from datetime import date
from decimal import Decimal

import pytest
from django.conf import settings

from ai.eval import dataset
from ai.eval.build_dataset import TODAY
from ai.eval.embed import DEFAULT_URL, TIMEOUT, ipv4_url
from ai.eval.evaluate import Evaluation
from ai.rag.answer import Source, build_messages, chat_options, summarize
from ai.rag.periods import detect_period
from ai.rag.profiles import UNTUNED, profile_for
from insights.spec import resolve_period

pytestmark = pytest.mark.skipif(
    not os.environ.get("RAG_LLM_EVAL"), reason="set RAG_LLM_EVAL=1 (needs a local Ollama)"
)

MODEL = os.environ.get("RAG_LLM_MODEL", "llama3.2:latest")
ANSWERABLE_SAMPLE = 12  # chat on CPU takes seconds per answer, so a fixed sample, not every one
CITATION = re.compile(r"\[(\d+)\]")
NOT_FOUND = re.compile(
    r"could(?: not|n't) find|not found|no (?:matching |relevant )?transactions?|"
    r"(?:does|do) not (?:show|contain|include)|no record|none of the",
    re.IGNORECASE,
)


def _sources(evaluation: Evaluation, ids: list[str]) -> list[Source]:
    rows = {row["id"]: row for row in evaluation.rows}
    texts = dict(zip(evaluation.ids, dataset.document_texts()))
    return [
        Source(
            n=n,
            transaction=row_id,
            date=date.fromisoformat(rows[row_id]["date"]),
            txn_type=rows[row_id]["txn_type"],
            amount=Decimal(rows[row_id]["amount"]),
            name=rows[row_id]["name"],
            category={"id": "", "name": rows[row_id]["category"], "color": ""},
            text=texts[row_id],
        )
        for n, row_id in enumerate(ids, start=1)
    ]


def _period(question: str, first: date) -> dict:
    detected = detect_period(question, TODAY)
    if detected:
        start, end = resolve_period(detected.date_filter, detected.date_filter, TODAY)
    else:
        start, end = first, TODAY
    return {"from": start.isoformat(), "to": end.isoformat()}


def _chat(base: str, messages: list[dict]) -> str:
    body = {"model": MODEL, "messages": messages, "stream": False, "options": chat_options()}
    request = urllib.request.Request(
        f"{base}/api/chat", json.dumps(body).encode(), {"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return json.load(response)["message"]["content"]


def test_answer_quality_report():
    base = ipv4_url(os.environ.get("OLLAMA_URL", DEFAULT_URL))
    evaluation = Evaluation()
    profile = profile_for(dataset.vectors()["model"])
    first = min(date.fromisoformat(row["date"]) for row in evaluation.rows)
    questions = dataset.questions()
    answerable = [q for q in evaluation.questions if q.relevant]
    step = max(1, len(answerable) // ANSWERABLE_SAMPLE)
    sample = answerable[::step][:ANSWERABLE_SAMPLE]

    cited_answers, valid, relevant_valid, invalid = 0, 0, 0, 0
    for question in sample:
        text = questions[question.index]["question"]
        ids = evaluation.search(question, "prefixed", profile, "hybrid")
        sources = _sources(evaluation, ids)
        shown = len(sources[: settings.RAG_TOP_K])
        messages = build_messages(text, sources, summarize(sources), _period(text, first), TODAY)
        numbers = {int(n) for n in CITATION.findall(_chat(base, messages))}
        good = {n for n in numbers if 1 <= n <= shown}
        invalid += len(numbers - good)
        valid += len(good)
        relevant_valid += sum(1 for n in good if sources[n - 1].transaction in question.relevant)
        cited_answers += bool(good)

    # No-answer questions find nothing in production, so the model is never called. To test the
    # model's own "not found", give it the rows an untuned search ranks closest: all unrelated.
    said_not_found, no_answer = 0, [q for q in evaluation.questions if not q.relevant]
    for question in no_answer:
        text = questions[question.index]["question"]
        ids = evaluation.search(question, "prefixed", UNTUNED, "vector")[:5]
        sources = _sources(evaluation, ids)
        messages = build_messages(text, sources, summarize(sources), _period(text, first), TODAY)
        said_not_found += bool(NOT_FOUND.search(_chat(base, messages)))

    citations = valid + invalid
    print(f"\nAnswer quality with {MODEL}, prompt from ai/rag/answer.py")
    print(f"  answers that cite:         {cited_answers}/{len(sample)}")
    print(
        f"  citation precision:        {relevant_valid}/{valid} valid citations point at a relevant row"
    )
    print(f"  invalid references:        {invalid}/{citations} citations")
    print(f"  'not found' when irrelevant: {said_not_found}/{len(no_answer)}")
    assert sample and no_answer

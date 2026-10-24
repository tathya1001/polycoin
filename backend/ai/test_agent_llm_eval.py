"""Opt-in quality of the panel builder with a real chat model: every evaluation case, through the
real workflow, with each prompt sent to a local Ollama.

Dev machine only, fictional data only; never in CI or production. It reports rather than gates,
because quality depends on the user's own model; the targets are printed next to each number:

    docker compose exec -e AGENT_LLM_EVAL=1 backend pytest ai/test_agent_llm_eval.py -s

AGENT_LLM_MODEL picks the chat model (default llama3.2:latest); OLLAMA_URL its address. On a
laptop CPU a reply takes 10-40 seconds, so the full set takes a while.

Measured:
- replies that parse: share of the model's replies that are a valid intent;
- valid panel: share of panel requests that end in a previewed panel, repairs included;
- exact panel: share of panel requests whose panel shows every expected field;
- per field: how often each expected field is right;
- not-a-panel recall and precision: questions turned away, and how often a turn-away was right.
"""

import json
import os
import statistics
import time
import urllib.request
from collections import defaultdict

import pytest
from django.utils import timezone

from ai.eval.agent import load_cases, run_case, seed
from ai.eval.embed import DEFAULT_URL, TIMEOUT, ipv4_url
from transactions.tests import make_user

pytestmark = pytest.mark.skipif(
    not os.environ.get("AGENT_LLM_EVAL"), reason="set AGENT_LLM_EVAL=1 (needs a local Ollama)"
)

MODEL = os.environ.get("AGENT_LLM_MODEL", "llama3.2:latest")
TARGETS = {
    "parse": 0.98,
    "valid": 0.90,
    "exact": 0.75,
    "field": 0.85,
    "recall": 0.80,
    "precision": 0.90,
}


def _ratio(part: int, whole: int) -> float:
    return part / whole if whole else 1.0


def _line(label: str, part: int, whole: int, target: float) -> str:
    value = _ratio(part, whole)
    verdict = "pass" if value >= target else "FAIL"
    return f"  {label:<28}{part:>4}/{whole:<4} {value:6.1%}  target {target:.0%}  {verdict}"


@pytest.mark.django_db
def test_panel_builder_quality_report():
    base = ipv4_url(os.environ.get("OLLAMA_URL", DEFAULT_URL))
    seconds, prompt_tokens = [], []

    def ask(case_id: str, index: int, request: dict) -> str:
        """What the browser does: the server's chat request, sent to Ollama as it is."""
        body = {
            "model": MODEL,
            "messages": request["messages"],
            "format": request["format"],
            "options": request["options"],
            "stream": False,
        }
        started = time.perf_counter()
        call = urllib.request.Request(
            f"{base}/api/chat", json.dumps(body).encode(), {"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(call, timeout=TIMEOUT) as response:
            data = json.load(response)
        seconds.append(time.perf_counter() - started)
        prompt_tokens.append(data.get("prompt_eval_count") or 0)
        return data["message"]["content"]

    results = []
    for number, case in enumerate(load_cases()):
        user = make_user(f"eval{number}@example.com")
        seed(user, timezone.localdate())
        results += run_case(user, case, ask)

    calls = sum(result.calls for result in results)
    parsed = sum(result.parsed for result in results)
    panels = [result for result in results if result.wants_panel]
    questions = [result for result in results if not result.wants_panel]
    turned_away = [result for result in results if result.seen["kind"] == "not_a_panel"]
    field_hits, field_totals = defaultdict(int), defaultdict(int)
    for result in panels:
        for name, ok in result.fields.items():
            if name != "kind":
                field_totals[name] += 1
                field_hits[name] += ok

    print(f"\nPanel builder with {MODEL}: {len(results)} turns, {calls} model replies")
    print(_line("replies that parse", parsed, calls, TARGETS["parse"]))
    print(_line("valid panel (with repairs)", sum(r.seen["kind"] == "panel" for r in panels),
                len(panels), TARGETS["valid"]))  # fmt: skip
    print(_line("exact panel", sum(r.correct for r in panels), len(panels), TARGETS["exact"]))
    for name in sorted(field_totals):
        print(_line(f"  {name}", field_hits[name], field_totals[name], TARGETS["field"]))
    print(_line("not-a-panel recall", sum(r.correct for r in questions), len(questions),
                TARGETS["recall"]))  # fmt: skip
    print(_line("not-a-panel precision", sum(not r.wants_panel for r in turned_away),
                len(turned_away), TARGETS["precision"]))  # fmt: skip
    if seconds:
        ordered = sorted(seconds)
        p95 = ordered[min(len(ordered) - 1, int(0.95 * len(ordered)))]
        print(f"  seconds per reply: median {statistics.median(seconds):.1f}, p95 {p95:.1f}")
        print(f"  prompt tokens: max {max(prompt_tokens)}")
    errors = [f"{r.case}: {r.error}" for r in results if r.error]
    if errors:
        print("  ended with an error: " + ", ".join(errors))
    misses = [f"{r.case} ({', '.join(n for n, ok in r.fields.items() if not ok)})"
              for r in results if not r.correct]  # fmt: skip
    if misses:
        print("  wrong: " + "; ".join(misses))
    assert results and calls

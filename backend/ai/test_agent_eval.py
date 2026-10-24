"""The panel builder's evaluation set, checked in CI with the replies a correct model gives.

Each case's golden replies go through the real workflow (grounding, compiler, validator,
preview) and must build exactly the expected panel in one model call per turn. That keeps the
dataset honest, so the opt-in run with a real model (test_agent_llm_eval.py) measures the
model and not a mistake in the cases.
"""

import pytest
from django.utils import timezone

from ai.agent.schema import parse_intent
from ai.eval.agent import FIELDS, SPENDING, golden_answer, golden_reply, load_cases, run_case, seed
from transactions.tests import make_user

CASES = load_cases()


def test_the_set_is_big_enough_and_mixed():
    turns = [turn for case in CASES for turn in case["turns"]]
    questions = [turn for turn in turns if turn["expect"].get("kind") == "not_a_panel"]
    chains = [case for case in CASES if len(case["turns"]) > 1]
    assert len(CASES) >= 45 and len(questions) >= 5 and len(chains) >= 4
    assert len({case["id"] for case in CASES}) == len(CASES)


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_each_turn_is_well_formed(case):
    for turn in case["turns"]:
        assert set(turn) == {"message", "golden", "expect"}
        assert set(turn["expect"]) <= set(FIELDS)
        assert 0 < len(turn["message"]) <= 300
        parse_intent(golden_reply(turn["golden"]))  # a reply the model could really give


def test_merchants_are_the_fictional_ones():
    known = [name.lower() for name, _, _ in SPENDING]
    for case in CASES:
        for turn in case["turns"]:
            merchant = turn["golden"].get("merchant")
            assert merchant is None or any(merchant.lower() in name for name in known)


@pytest.mark.django_db
@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_golden_replies_build_the_expected_panel(case):
    user = make_user("eval@example.com")
    seed(user, timezone.localdate())
    for result in run_case(user, case, golden_answer(CASES)):
        assert result.error is None, result.error
        assert result.correct, {name: ok for name, ok in result.fields.items() if not ok}
        assert result.calls == result.parsed == 1

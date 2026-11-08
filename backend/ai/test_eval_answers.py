"""The answer checks on hand-written answers: no model needed."""

from decimal import Decimal

import pytest

from ai.eval import answers
from ai.eval.answers import Result, facts, made_up, quotes

PROMPT = (
    "Today is 2026-10-15. The search covered 2025-11-01 to 2026-10-15.\n"
    "Summary of all 3 matching transactions: debits total ₹4500.00, credits total ₹0.00, dated "
    "2026-03-05 to 2026-05-05.\n"
    "[1] 2026-03-05 | debit | ₹1500.00 | Health | FITZONE GYM\n"
    "[2] 2026-04-05 | debit | ₹1500.00 | Health | FITZONE GYM\n"
    "[3] 2026-05-05 | debit | ₹1500.00 | Health | FITZONE GYM\n"
    "Question: How much did I spend on the gym?"
)


def test_facts_read_amounts_counts_and_dates_but_not_citations():
    found = facts("You paid ₹1,500.00 three times [2], 3 payments, on 5 March 2026 and 2026-04-05.")
    assert found.numbers == {Decimal("1500"), Decimal("3")}
    assert found.dates == {(2026, 3, 5), (2026, 4, 5)}


def test_citation_lists_and_ranges_are_not_amounts_but_only_lists_count_as_citations():
    text = "Paid ₹199 [1-10], ₹500 [4, 6, 16] and ₹20 [2–3]."
    assert facts(text).numbers == {Decimal("199"), Decimal("500"), Decimal("20")}
    assert answers.cited_numbers(text) == [4, 6, 16]  # as the page links them


@pytest.mark.parametrize(
    "text, date",
    [("on March 5, 2026", (2026, 3, 5)), ("on 5th Mar", (None, 3, 5)), ("May 5", (None, 5, 5))],
)
def test_facts_read_the_usual_ways_of_writing_a_date(text, date):
    assert facts(text).dates == {date}


def test_an_answer_that_quotes_the_prompt_makes_nothing_up():
    answer = "You spent ₹4,500 on the gym across 3 payments, from 5 March 2026 to May 5 [1][2][3]."
    assert made_up(answer, PROMPT) == []


def test_an_amount_the_model_added_up_itself_counts_as_made_up():
    assert made_up("You spent ₹3,000 in March and April [1][2].", PROMPT) == ["3000"]


def test_a_date_that_is_not_in_the_prompt_counts_as_made_up():
    assert made_up("Your last payment was on 2026-06-05 [3].", PROMPT) == ["2026-06-05"]
    assert made_up("Your last payment was on 6 June [3].", PROMPT) == ["?-06-06"]


def test_a_year_on_its_own_is_known_when_a_prompt_date_has_it():
    assert made_up("All of them were in 2026.", PROMPT) == []
    assert made_up("All of them were in 2024.", PROMPT) == ["2024"]


def test_quoting_a_total_ignores_formatting():
    assert quotes("That comes to ₹4,500.00 in total.", "4500.00")
    assert quotes("₹4500", "4500.00")
    assert not quotes("₹4,000", "4500.00")


def _result(**overrides) -> Result:
    values = dict(question="q", kind="exact", answer="", cited=[1], valid=1, relevant_valid=1,
                  invalid=0, made_up=[])  # fmt: skip
    return Result(**{**values, **overrides})


def test_a_wrong_total_is_blamed_on_search_when_the_summary_was_already_wrong():
    assert _result(total_question=True, summary_right=False, quotes_total=True).error == "retrieval"


def test_a_wrong_total_is_blamed_on_the_model_when_the_summary_was_right():
    assert (
        _result(total_question=True, summary_right=True, quotes_total=False).error == "generation"
    )
    made = _result(total_question=True, summary_right=True, quotes_total=True, made_up=["3000"])
    assert made.error == "generation"
    right = _result(total_question=True, summary_right=True, quotes_total=True)
    assert right.error is None


def test_the_summary_counts_answers_and_unrelated_rows_apart():
    numbers = answers.summary(
        [
            _result(question="a", total_question=True, summary_right=True, quotes_total=True),
            _result(question="b", valid=0, cited=[], relevant_valid=0, made_up=["9"]),
            _result(question="c", cited=[1, 9], valid=1, invalid=1),
            _result(
                question="d",
                kind="no-answer",
                cited=[],
                valid=0,
                relevant_valid=0,
                said_not_found=True,
            ),  # fmt: skip
        ]
    )
    assert numbers["answers"] == 3
    assert numbers["cites"] == pytest.approx(2 / 3, abs=1e-4)
    assert numbers["invalid references"] == pytest.approx(1 / 3, abs=1e-4)
    assert numbers["made-up-number rate"] == pytest.approx(1 / 3, abs=1e-4)
    assert (numbers["total questions"], numbers["totals right"]) == (1, 1.0)
    assert numbers["not found when unrelated"] == 1.0

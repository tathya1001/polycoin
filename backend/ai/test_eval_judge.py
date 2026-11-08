"""The labelling sheet: its sample, its layout, and reading a person's labels back."""

import json

import pytest

from ai.eval import judge, results
from ai.eval.judge import Item


def _item(qid: str, kind: str = "exact", unrelated: bool = False) -> Item:
    return Item(
        question_id=qid,
        kind=kind,
        question=f"Question {qid}?",
        period="2025-11-01 to 2026-10-15",
        summary="Summary of all 1 matching transactions: debits total ₹10.00, ...",
        rows=[("1", "2026-01-05", "debit", "₹10.00", "Food", "TASTY CAFE")],
        answer="You paid ₹10.00 [1].\n\nThat's all.",
        unrelated=unrelated,
    )


ITEMS = [_item(f"a{n}", kind="exact" if n % 2 else "typo") for n in range(20)] + [
    _item(f"u{n}", kind="no-answer", unrelated=True) for n in range(6)
]


def test_the_sample_is_even_deterministic_and_leaves_out_the_examples():
    first = judge.sample(ITEMS, count=10, unrelated=3, exclude={"a0", "a1"})
    assert [i.question_id for i in first] == [
        i.question_id for i in judge.sample(list(reversed(ITEMS)), 10, 3, {"a0", "a1"})
    ]
    assert len(first) == 10 and sum(i.unrelated for i in first) == 3
    assert not {"a0", "a1"} & {i.question_id for i in first}
    assert {i.kind for i in first if not i.unrelated} == {"exact", "typo"}


def test_an_item_shows_what_the_model_was_given_and_quotes_every_answer_line():
    text = judge.render_item("L01", _item("a1"))
    assert text.startswith("### L01 · `a1`")
    assert "| 1 | 2026-01-05 | debit | ₹10.00 | Food | TASTY CAFE |" in text
    assert "> You paid ₹10.00 [1].\n>\n> That's all." in text
    assert "- Faithful (1-5): \n- Relevant (1-5): \n" in text


def test_filled_labels_are_read_back_and_blanks_stay_empty():
    sheet = "\n".join(
        [
            judge.render_item("Example 1", _item("x"), {"faithful": 5, "relevant": 5}),
            judge.render_item("L01", _item("a1"), {"faithful": 4, "relevant": 3, "note": "ok"}),
            judge.render_item("L02", _item("a2")),
        ]
    )
    assert judge.read_labels(sheet) == {
        "a1": {"faithful": 4, "relevant": 3, "held_out": False},
        "a2": {"faithful": None, "relevant": None, "held_out": False},
    }


def test_a_held_out_sheet_numbers_items_h_and_leaves_out_labelled_answers():
    items = ITEMS + [_item(qid) for qid in judge.EXAMPLES]  # the sheet shows them first
    sheet = judge.render_sheet("run", items, count=6, unrelated=2)
    labelled = set(judge.read_labels(sheet))
    held_out = judge.render_sheet(
        "run", items, count=6, unrelated=2, exclude=labelled, prefix=judge.HELD_OUT
    )
    assert "### H01 · " in held_out and "### L01 · " not in held_out
    tested = judge.read_labels(held_out)
    assert len(tested) == 6 and labelled.isdisjoint(tested)
    assert all(v["held_out"] for v in tested.values())
    assert not any(v["held_out"] for v in judge.read_labels(sheet).values())
    assert len(judge.read_labels(sheet + held_out)) == 12  # both sheets read together


def test_the_examples_use_the_rubrics_scale():
    assert all(1 <= e["faithful"] <= 5 and 1 <= e["relevant"] <= 5 for e in judge.EXAMPLES.values())


# --- the judge model and agreement --------------------------------------------------------------


def test_perfect_agreement_is_one_and_a_near_miss_costs_less_than_a_far_one():
    scores = [1, 2, 3, 4, 5, 5]
    assert judge.weighted_kappa(scores, scores) == pytest.approx(1.0)
    near = judge.weighted_kappa(scores, [2, 2, 3, 4, 5, 4])
    far = judge.weighted_kappa(scores, [5, 2, 3, 4, 5, 1])
    assert far < near < 1 and near > 0  # two 1-vs-5 misses make it worse than chance (< 0)


def test_kappa_matches_a_hand_computed_value():
    # 2x2 on a 5-point scale: scores 1 and 5 only. Observed: 3 agree on 1, 1 says 1/5.
    # p(a=1)=1, p(b=1)=0.75, p(b=5)=0.25 -> expected weighted disagreement 0.25,
    # observed 0.25 -> kappa 0 (no better than chance given these marginals).
    assert judge.weighted_kappa([1, 1, 1, 1], [1, 1, 1, 5]) == pytest.approx(0.0)


def test_kappa_cant_be_computed_from_one_item_or_one_constant_score():
    assert judge.weighted_kappa([3], [3]) != judge.weighted_kappa([3], [3])  # NaN
    assert judge.weighted_kappa([5, 5], [5, 5]) != judge.weighted_kappa([5, 5], [5, 5])
    with pytest.raises(ValueError):
        judge.weighted_kappa([1, 2], [1])


def test_agreement_compares_only_items_both_scored():
    reference = {"a": {"faithful": 5}, "b": {"faithful": 3}, "c": {"faithful": None}}
    judged = {"a": {"faithful": 5}, "b": {"faithful": 2}, "d": {"faithful": 1}}
    result = judge.agreement(reference, judged, "faithful", resamples=50)
    assert result["n"] == 2 and result["exact"] == 0.5 and result["within_1"] == 1.0
    assert judge.agreement({}, judged, "faithful") == {"n": 0}


def test_a_kappa_change_is_paired_and_called_real_only_when_its_interval_leaves_out_zero():
    labels = [1, 2, 3, 4, 5] * 6
    reference = {f"q{k}": {"faithful": s} for k, s in enumerate(labels)}
    poor = {f"q{k}": {"faithful": 3} for k in range(len(labels))}
    poor["q0"]["faithful"] = 1  # not constant, so kappa is defined
    good = {f"q{k}": {"faithful": s} for k, s in enumerate(labels)}
    better = judge.kappa_change(reference, poor, good, "faithful", resamples=200)
    assert better["n"] == 30 and better["after"] == 1.0 and better["change"] > 0
    assert better["real"] and better["change_ci"][0] > 0
    same = judge.kappa_change(reference, good, good, "faithful", resamples=200)
    assert same["change"] == 0 and not same["real"]
    assert judge.kappa_change(reference, poor, {}, "faithful") == {"n": 0}


def test_a_panel_averages_the_judges_rounding_a_half_up_on_answers_all_scored():
    first = {"a": {"faithful": 4, "relevant": 5}, "b": {"faithful": 2}, "c": {"faithful": 1}}
    second = {"a": {"faithful": 5, "relevant": 3}, "b": {"faithful": 2, "relevant": 4}}
    assert judge.panel([first, second]) == {
        "a": {"faithful": 5, "relevant": 4},  # 4.5 -> 5, 4.0 -> 4
        "b": {"faithful": 2},  # relevant only from one judge
    }


def test_a_panel_keeps_a_score_every_judge_took_from_a_rule_marked_as_a_rule():
    rule = "no row answers; it says it found nothing"
    first = {"a": {"faithful": 5, "relevant": 5, "relevant_rule": rule}, "b": {"relevant": 4}}
    second = {"a": {"faithful": 4, "relevant": 5, "relevant_rule": rule}, "b": {"relevant": 3}}
    combined = judge.panel([first, second])
    assert combined["a"] == {"faithful": 5, "relevant": 5, "relevant_rule": rule}
    assert "relevant_rule" not in combined["b"]


def test_a_judgment_must_have_both_scores_in_range():
    reply = '{"reason": "the total matches", "faithful": 5, "relevant": 4}'
    assert judge.parse_judgment(reply) == {
        "faithful": 5,
        "relevant": 4,
        "reason": "the total matches",
    }
    for bad in ('{"faithful": 6, "relevant": 4}', '{"faithful": 5}', "not json"):
        with pytest.raises((ValueError, KeyError)):
            judge.parse_judgment(bad)


def test_the_judge_sees_the_rubric_the_examples_and_what_the_model_was_given():
    system, user = judge.judge_messages(_item("a1"))
    assert judge.RUBRIC in system["content"] and "haircuts: Faithful 2" in system["content"]
    assert "[1] 2026-01-05 | debit | ₹10.00 | Food | TASTY CAFE" in user["content"]
    assert "<answer>\nYou paid ₹10.00 [1].\n\nThat's all.\n</answer>" in user["content"]


def test_cached_scores_are_kept_per_judge_run_and_prompt(tmp_path, monkeypatch):
    monkeypatch.setattr(results, "RESULTS", tmp_path)
    assert judge.load_judgments("qwen2.5:7b", "llama-text-v2") == {}
    judge.save_judgments("qwen2.5:7b", "llama-text-v2", {"a1": {"faithful": 4, "relevant": 5}})
    assert judge.load_judgments("qwen2.5:7b", "llama-text-v2")["a1"]["faithful"] == 4
    assert judge.load_judgments("gemma3:4b", "llama-text-v2") == {}
    assert judge.load_judgments("qwen2.5:7b", "llama-text-v2", "v2") == {}
    assert judge.cache_label("qwen2.5:7b", "llama-text-v2") == "qwen2-5-7b--llama-text-v2"
    assert judge.cache_label("qwen3:8b", "llama-text-v2", "v2") == "qwen3-8b--llama-text-v2--v2"
    long = judge.cache_label("some-very-long-model-name:latest", "a-long-answers-run-label", "v2")
    assert len(long) <= 48 and long.endswith("--v2")


# --- the checked judge (v2) ---------------------------------------------------------------------


def _checked_item(answer: str, answering: tuple[int, ...] = (1, 2)) -> Item:
    return Item(
        question_id="q",
        kind="exact",
        question="How much did I spend at Tasty Cafe?",
        period="2025-11-01 to 2026-10-15",
        summary="Summary of all 3 matching transactions: debits total ₹60.00, credits total "
        "₹0.00, dated 2026-01-05 to 2026-03-05.",
        rows=[
            ("1", "2026-01-05", "debit", "₹10.00", "Food", "TASTY CAFE tastycafe"),
            ("2", "2026-02-05", "debit", "₹20.00", "Food", "TASTY CAFE"),
            ("3", "2026-03-05", "debit", "₹30.00", "Bills", "CITY POWER BILL"),
        ],
        answer=answer,
        unrelated=False,
        answering=answering,
    )


def test_payee_groups_count_the_rows_of_each_payee_and_type():
    assert judge.payee_groups(_checked_item("")) == [
        "- TASTY CAFE (debit): 2 transactions, rows 1-2, ₹10.00 to ₹20.00",
        "- CITY POWER (debit): 1 transaction, row 3, ₹30.00 each",
    ]


def test_fact_checks_say_where_each_amount_and_date_comes_from():
    checks = judge.fact_checks(
        _checked_item("You spent ₹60.00 in all: ₹10.00 on 2026-01-05 [1] and ₹20 on 9 May [1]. "
                      "That is ₹30.00 [3], or ₹15.50 a visit.")
    )  # fmt: skip
    assert "- ₹60.00: the summary's debit total" in checks
    assert "- ₹10.00: the amount of row 1" in checks
    assert "- ₹15.50: in no row and not a summary total" in checks
    assert "- ₹20.00 next to [1]: row 1 is ₹10.00, not ₹20.00" in checks  # cites the wrong row
    assert not any("₹30.00 next to" in c for c in checks)  # cited right
    assert "- 2026-01-05: the date of row 1" in checks
    assert "- --05-09: the date of no row" in checks
    assert checks[-1].startswith("- The only totals given: debits ₹60.00, credits ₹0.00")


def test_a_citation_just_before_its_amount_is_not_a_miscitation():
    checks = judge.fact_checks(
        _checked_item("On [1], you spent ₹10.00 at Tasty Cafe, and on [2], you spent ₹20.00.")
    )
    assert not any("next to" in c for c in checks)


def test_a_citation_in_the_next_sentence_doesnt_belong_to_the_amount():
    checks = judge.fact_checks(_checked_item("You spent ₹20.00. Then [1] was a coffee."))
    assert not any("next to" in c for c in checks)


def test_a_made_up_amount_is_not_also_reported_as_a_wrong_citation():
    checks = judge.fact_checks(_checked_item("The total is ₹99.00 [1]."))
    assert checks[0] == "- ₹99.00: in no row and not a summary total"
    assert not any("row 1 is" in c for c in checks)


@pytest.mark.parametrize(
    "severities, score",
    [
        ([], 5),
        (["minor", "minor"], 4),
        (["wrong"], 3),
        (["wrong", "minor"], 3),
        (["wrong", "wrong"], 2),
        (["wrong_total"], 2),
        (["minor", "unrelated"], 1),
    ],
)
def test_the_faithfulness_score_follows_the_rubric(severities, score):
    assert judge.faithful_score([{"severity": s} for s in severities]) == score


def test_errors_must_quote_the_answer_except_an_unrelated_answer():
    item = _checked_item("You spent ₹60.00 at Tasty Cafe [1].")
    reply = json.dumps(
        {
            "analysis": "...",
            "errors": [
                {"quote": "spent ₹60.00 at Tasty Cafe", "problem": "x", "severity": "wrong"},
                {"quote": "does not mention the dates", "problem": "y", "severity": "minor"},
                {"quote": "", "problem": "z", "severity": "unrelated"},
            ],
        }
    )
    parsed = judge.parse_faithful(reply, item)
    assert [e["problem"] for e in parsed["faithful_errors"]] == ["x", "z"]
    assert [e["problem"] for e in parsed["faithful_dropped"]] == ["y"]
    assert parsed["faithful"] == 1
    bad = json.dumps({"analysis": "", "errors": [{"quote": "a", "problem": "b", "severity": "?"}]})
    with pytest.raises(ValueError):
        judge.parse_faithful(bad, item)


def test_a_relevance_reply_must_have_a_score_in_range():
    reply = '{"wants": "a total", "matching_rows": "1-2", "analysis": "ok", "relevant": 4}'
    assert judge.parse_relevant(reply)["relevant"] == 4
    with pytest.raises((ValueError, KeyError)):
        judge.parse_relevant('{"wants": "", "matching_rows": "", "analysis": "", "relevant": 0}')


def test_v1_scores_both_in_one_call_and_v2_makes_one_call_per_score():
    item = _checked_item("You spent ₹60.00 [1].")
    assert [name for name, _, _ in judge.judge_calls(item, "v1")] == ["both"]
    calls = {name: messages for name, messages, _ in judge.judge_calls(item, "v2")}
    assert list(calls) == ["faithful", "relevant"]
    assert "- ₹60.00: the summary's debit total" in calls["faithful"][1]["content"]
    assert "- TASTY CAFE (debit): 2 transactions" in calls["relevant"][1]["content"]
    assert "Automatic checks" not in calls["relevant"][1]["content"]


# --- the reference-guided judge (v3) ------------------------------------------------------------


def test_the_reference_says_which_rows_answer_and_what_the_answer_covers():
    item = _checked_item("You spent ₹20.00 [2] and ₹30.00 at Tasty Cafe [3].")
    assert judge.reference_facts(item) == [
        "- Rows 1-2 answer the question: 2 transactions, dated 2026-01-05 to 2026-02-05. Every "
        "other row shown is about something else."
    ]
    assert judge.coverage_facts(item) == [
        "- The answer cites 1 of the 2 answering rows; it doesn't cite row 1.",
        "- It also cites rows that don't answer the question: [3] CITY POWER BILL",
        "- It says it found nothing: no.",
    ]


def test_the_reference_for_a_question_no_row_answers():
    item = _checked_item("I couldn't find any transactions for that.", answering=())
    assert judge.reference_facts(item) == [
        "- No row answers the question: every row shown is about something else."
    ]
    assert judge.coverage_facts(item)[-1] == "- It says it found nothing: yes."


def test_an_amount_in_no_row_is_an_error_and_a_wrong_total_when_called_a_total():
    errors = judge.unsupported_amounts(
        _checked_item("The total is ₹45.00 [1]. You also paid ₹12.50 once. Row 1 was ₹10.00.")
    )
    assert [(e["severity"], e["problem"]) for e in errors] == [
        ("wrong_total", "₹45.00 is in no row and isn't a summary total"),
        ("wrong", "₹12.50 is in no row and isn't a summary total"),
    ]
    assert judge.unsupported_amounts(_checked_item("You spent ₹60.00 in all: ₹10.00 [1].")) == []


def test_v3_counts_an_error_found_by_code_and_by_the_model_once():
    item = _checked_item("The total is ₹45.00 [1].")
    reply = json.dumps(
        {
            "analysis": "...",
            "errors": [
                {"quote": "The total is ₹45.00", "problem": "made up", "severity": "wrong_total"},
                {"quote": "[1]", "problem": "row 1 is not all", "severity": "wrong"},
            ],
        }
    )
    parsed = judge.read_reply("faithful", reply, item, "v3")
    assert [e["problem"] for e in parsed["faithful_errors"]] == [
        "₹45.00 is in no row and isn't a summary total",
        "row 1 is not all",
    ]
    assert parsed["faithful"] == 2


@pytest.mark.parametrize(
    "answer, decided",
    [
        ("I couldn't find any transactions for that.", {"relevant": 5}),
        ("You spent ₹30.00 on it [3].", {"relevant": 2, "faithful": 1}),
    ],
)
def test_a_question_no_row_answers_is_scored_by_the_rubrics_rule(answer, decided):
    item = _checked_item(answer, answering=())
    scores = {k: v for k, v in judge.ruled(item, "v3").items() if not k.endswith("_rule")}
    assert scores == decided
    assert [name for name, _, _ in judge.judge_calls(item, "v3")] == [
        m for m in judge.METRICS if m not in decided
    ]
    assert judge.ruled(item, "v2") == {}


def test_v3_gives_both_calls_the_reference_and_only_faithfulness_the_checks():
    item = _checked_item("You spent ₹20.00 [2].")
    assert judge.ruled(item, "v3") == {}
    calls = {name: messages[1]["content"] for name, messages, _ in judge.judge_calls(item, "v3")}
    assert list(calls) == ["faithful", "relevant"]
    for content in calls.values():
        assert "Rows 1-2 answer the question" in content
    assert "Automatic checks" in calls["faithful"]
    assert "Automatic checks" not in calls["relevant"]


def test_the_labelling_sheet_never_shows_the_reference():
    sheet_item = judge.render_item("L01", _checked_item("You spent ₹20.00 [2]."))
    assert "answer the question" not in sheet_item and "Reference" not in sheet_item


def test_v4_words_the_found_nothing_fact_plainly_and_gives_no_cited_row_counts():
    item = _checked_item("You spent ₹20.00 [2].")
    calls = {name: messages[1]["content"] for name, messages, _ in judge.judge_calls(item, "v4")}
    assert "The answer gives transactions; it does not say that none match." in calls["faithful"]
    assert "It says it found nothing" not in calls["faithful"]
    assert "The answer cites" not in calls["faithful"]  # no "cites 1 of the 2 answering rows"
    assert "The answer cites" not in calls["relevant"]  # coverage is judged from the words
    systems = {name: messages[0]["content"] for name, messages, _ in judge.judge_calls(item, "v4")}
    assert "Judge coverage from what the answer SAYS" in systems["relevant"]
    found_nothing = _checked_item("I couldn't find any transactions for that.", answering=(1,))
    assert "- The answer says no transaction matches." in judge.coverage_facts(found_nothing, "v4")


def test_v4_scores_like_v3_where_the_rubric_or_code_decides():
    no_match = _checked_item("You spent ₹30.00 on it [3].", answering=())
    assert judge.ruled(no_match, "v4") == judge.ruled(no_match, "v3")
    reply = json.dumps({"analysis": "", "errors": []})
    made_up = _checked_item("The total is ₹45.00 [1].")
    assert judge.read_reply("faithful", reply, made_up, "v4")["faithful"] == 2

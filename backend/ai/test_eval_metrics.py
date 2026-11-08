"""The evaluation's own arithmetic: statistics, per-question scoring, saved runs and comparisons.
Pure functions on hand-made inputs; no model, no database."""

from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from ai.eval import results, search_report, stats
from ai.eval.evaluate import Metrics, Outcome, score_question

# --- stats ---------------------------------------------------------------------------------------


def test_the_bootstrap_of_a_constant_is_that_constant():
    assert stats.bootstrap_ci([0.5] * 10) == stats.Interval(0.5, 0.5, 0.5)


def test_the_bootstrap_interval_holds_the_mean_and_repeats_exactly():
    values = [1, 0, 1, 1, 0, 1, 1, 1, 0, 1]
    first = stats.bootstrap_ci(values)
    assert first.low <= first.mean == 0.7 <= first.high
    assert first.low < first.high
    assert stats.bootstrap_ci(values) == first


def test_the_bootstrap_refuses_no_values():
    with pytest.raises(ValueError):
        stats.bootstrap_ci([])


def test_a_paired_gain_on_every_question_is_real():
    change = stats.paired_bootstrap([0, 0, 0, 0], [1, 1, 1, 1])
    assert change == stats.Interval(1.0, 1.0, 1.0)
    assert change.excludes_zero()


def test_a_paired_change_that_cancels_out_could_be_noise():
    change = stats.paired_bootstrap([0, 1, 0, 1, 0, 1], [1, 0, 1, 0, 1, 0])
    assert change.mean == 0 and not change.excludes_zero()


def test_paired_results_must_cover_the_same_questions():
    with pytest.raises(ValueError):
        stats.paired_bootstrap([1, 0], [1])
    with pytest.raises(ValueError):
        stats.mcnemar_exact([True], [True, False])


def _pairs(right_to_wrong: int, wrong_to_right: int, same: int = 3):
    before = [True] * right_to_wrong + [False] * wrong_to_right + [True] * same
    after = [False] * right_to_wrong + [True] * wrong_to_right + [True] * same
    return before, after


@pytest.mark.parametrize(
    ("b", "c", "expected"),
    [
        (0, 5, 2 / 2**5),  # 0.0625: five fixes and no breaks is not yet significant
        (1, 9, 2 * (1 + 10) / 2**10),  # 0.0215
        (3, 3, 1.0),  # balanced: capped at 1
        (0, 0, 1.0),  # no disagreement, no evidence
    ],
)
def test_mcnemar_matches_hand_computed_p_values(b, c, expected):
    assert stats.mcnemar_exact(*_pairs(b, c)) == pytest.approx(expected)


def test_folds_cover_every_item_once_with_a_fair_share_of_each_stratum():
    ids = [f"q{n}" for n in range(23)]
    strata = ["a"] * 10 + ["b"] * 8 + ["c"] * 5
    folds = stats.stratified_folds(ids, strata, k=5)
    assert sorted(p for fold in folds for p in fold) == list(range(23))
    assert max(map(len, folds)) - min(map(len, folds)) <= 1
    for stratum in "abc":
        counts = [sum(1 for p in fold if strata[p] == stratum) for fold in folds]
        assert max(counts) - min(counts) <= 1, (stratum, counts)


def test_folds_depend_on_the_ids_not_the_file_order():
    ids = [f"q{n}" for n in range(12)]
    strata = ["a", "b"] * 6
    folds = stats.stratified_folds(ids, strata, k=3)
    reordered = list(reversed(range(12)))
    folds_again = stats.stratified_folds(
        [ids[i] for i in reordered], [strata[i] for i in reordered], k=3
    )
    by_id = sorted(sorted(ids[p] for p in fold) for fold in folds)
    by_id_again = sorted(sorted(ids[reordered[p]] for p in fold) for fold in folds_again)
    assert by_id == by_id_again


@pytest.mark.parametrize(
    ("ids", "strata", "k"),
    [(["a", "a"], ["x", "x"], 2), (["a", "b"], ["x"], 2), (["a", "b"], ["x", "x"], 3)],
)
def test_folds_refuse_bad_input(ids, strata, k):
    with pytest.raises(ValueError):
        stats.stratified_folds(ids, strata, k)


# --- per-question scoring ------------------------------------------------------------------------

AMOUNTS = {
    "r1": ("debit", Decimal("100.00")),
    "r2": ("debit", Decimal("250.50")),
    "r3": ("debit", Decimal("40.00")),
    "x1": ("debit", Decimal("999.00")),
    "c1": ("credit", Decimal("500.00")),
}
RELEVANT = frozenset({"r1", "r2", "r3"})


def _score(found, relevant=RELEVANT, in_prompt=20):
    return score_question("q", "kind", found, relevant, AMOUNTS, in_prompt)


def test_finding_exactly_the_relevant_rows_is_perfect():
    outcome = _score(["r2", "r1", "r3"])
    assert (outcome.precision, outcome.recall, outcome.f1) == (1.0, 1.0, 1.0)
    assert outcome.exact_total and outcome.reciprocal_rank == 1.0 and outcome.recall_at_5 == 1.0


def test_one_extra_row_of_the_same_type_makes_the_total_wrong():
    outcome = _score(["r1", "r2", "r3", "x1"])
    assert outcome.recall == 1.0 and outcome.precision == 0.75
    assert not outcome.exact_total


def test_only_the_relevant_rows_type_is_totalled():
    # The summary shows debits and credits apart, so a stray credit leaves the debit total right.
    assert _score(["r1", "r2", "r3", "c1"]).exact_total


def test_a_missing_row_makes_the_total_wrong_and_ranks_count_from_one():
    outcome = _score(["x1", "c1", "r1", "r2"])
    assert outcome.reciprocal_rank == pytest.approx(1 / 3)
    assert outcome.recall == pytest.approx(2 / 3) and not outcome.exact_total


def test_recall_at_5_is_capped_by_the_number_of_relevant_rows():
    many = {f"m{n}": ("debit", Decimal(1)) for n in range(12)}
    found = [f"m{n}" for n in range(5)]
    outcome = score_question("q", "kind", found, frozenset(many), many, 20)
    assert outcome.recall_at_5 == 1.0 and outcome.recall == pytest.approx(5 / 12)


def test_recall_in_prompt_counts_only_the_rows_the_model_reads():
    assert _score(["x1", "c1", "r1"], in_prompt=2).recall_in_prompt == 0.0
    assert _score(["x1", "c1", "r1"], in_prompt=3).recall_in_prompt == pytest.approx(1 / 3)


def test_finding_nothing_for_an_answerable_question_scores_zero():
    outcome = _score([])
    assert outcome.empty and outcome.f1 == 0.0 and not outcome.exact_total


def test_a_no_answer_question_is_right_only_when_nothing_is_found():
    assert _score([], relevant=frozenset()).empty
    assert not _score(["x1"], relevant=frozenset()).empty
    assert not _score([], relevant=frozenset()).answerable


def test_metrics_average_over_answerable_questions_and_count_no_match_apart():
    outcomes = [
        _score(["r1", "r2", "r3"]),  # f1 1, exact
        _score(["r1", "r2", "r3", "x1"]),  # f1 6/7, not exact
        _score([], relevant=frozenset()),  # no-answer, right
        _score(["x1"], relevant=frozenset()),  # no-answer, wrong
    ]
    metrics = Metrics.of(outcomes)
    assert metrics.set_f1 == pytest.approx((1 + 6 / 7) / 2)
    assert metrics.exact_total == 0.5 and metrics.no_match == 0.5
    # Every question counts once: F1 for the two with an answer, found-nothing for the others.
    assert metrics.overall == pytest.approx((1 + 6 / 7 + 1 + 0) / 4)
    assert metrics.score == metrics.overall
    assert metrics.interval("set_f1").mean == pytest.approx(metrics.set_f1)
    assert metrics.interval("overall").mean == pytest.approx(metrics.overall)


# --- saved runs ----------------------------------------------------------------------------------


@pytest.fixture
def saved_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(results, "RESULTS", tmp_path)
    return tmp_path


def test_a_saved_run_loads_back_with_its_kind_label_and_save_time(saved_runs):
    results.save("search", "baseline", {"meta": {"x": 1}})
    loaded = results.load("search", "baseline")
    saved = datetime.fromisoformat(loaded.pop("saved"))
    assert loaded == {"kind": "search", "label": "baseline", "meta": {"x": 1}}
    assert abs(datetime.now() - saved) < timedelta(minutes=1)


def test_a_saved_run_is_kept_unless_overwrite_is_asked_for(saved_runs):
    results.save("search", "baseline", {"n": 1})
    with pytest.raises(FileExistsError):
        results.save("search", "baseline", {"n": 2})
    results.save("search", "baseline", {"n": 2}, overwrite=True)
    assert results.load("search", "baseline")["n"] == 2


@pytest.mark.parametrize("label", ["", "Baseline", "../x", "a b", "-x"])
def test_labels_are_plain_names(saved_runs, label):
    with pytest.raises(ValueError):
        results.save("search", label, {})


def test_loading_a_run_that_was_never_saved_says_how_to_save_it(saved_runs):
    with pytest.raises(FileNotFoundError, match="--record nothing"):
        results.load("search", "nothing")


def test_metadata_takes_the_commit_from_the_environment(monkeypatch):
    monkeypatch.setenv("GIT_COMMIT", "abc1234-dirty")
    assert results.metadata(model="m")["commit"] == "abc1234-dirty"
    monkeypatch.delenv("GIT_COMMIT")
    assert results.metadata()["commit"] == "unknown"


# --- comparing runs ------------------------------------------------------------------------------


def _run(fingerprint: str, exact: dict[str, bool]) -> dict:
    outcomes = [
        Outcome(
            q,
            "kind",
            answerable=True,
            empty=False,
            f1=1.0 if right else 0.5,
            recall_at_5=1.0,
            exact_total=right,
        )  # fmt: skip
        for q, right in exact.items()
    ]
    metrics = Metrics.of(outcomes)
    return {
        "meta": {"fingerprint": fingerprint},
        "production": metrics.as_dict(),
        "outcomes": [o.__dict__ for o in outcomes],
    }


def test_a_comparison_on_the_same_dataset_names_what_was_fixed_and_broken():
    before = _run("same", {"gym": False, "water": False, "rent": True})
    after = _run("same", {"gym": True, "water": False, "rent": False})
    text = search_report.compare(before, after)
    assert "fixed 1, broken 1" in text
    assert "fixed: gym" in text and "broken: rent" in text


def test_a_comparison_across_datasets_skips_the_paired_tests():
    text = search_report.compare(_run("old", {"gym": False}), _run("new", {"gym": True}))
    assert "no paired test" in text and "McNemar" not in text

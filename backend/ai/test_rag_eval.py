"""Retrieval quality on the committed evaluation set: CI's quality gate. Needs no model.

The vectors were made by a real embedding model (python manage.py embed_rag_eval), and the
ranking is the production code, so a change that makes search worse fails here. The table of
every configuration prints with:

    docker compose exec backend pytest ai/test_rag_eval.py -s

The full report, with confidence intervals and cross-validated scores, is
`python manage.py rag_eval`.
"""

import pytest

from ai.eval import dataset
from ai.eval.build_dataset import ANSWERABLE, TODAY, TYPES
from ai.eval.evaluate import FOLDS, MODES, WINDOW, Evaluation, production_variant
from ai.rag.periods import detect_period
from ai.rag.profiles import UNTUNED, base_name, profile_for

# The production configuration's scores on the dev set, with the suggested embedding model (its
# vectors are the committed ones; see its profile). Improvements pass; a drop fails. Recorded
# rounded down, so float noise can't fail an unchanged ranking. No-match is low because near-miss
# questions share words with rows that don't answer them.
BASELINE = {"recall_at_5": 0.823, "mrr": 0.820, "no_match": 0.44}
# The locked test set is written before any tuning and scored only for the final numbers. Its
# digest is pinned so its questions and answers can't be edited after results are seen.
LOCKED_TEST_SET = "7b57f059d79c7a6b600dde18cc3471680ce17e5ccf948b29f94f771f71a01008"
MINIMUM_SIZE = {"dev": (300, 105, 20), "test": (200, 40, 10)}  # rows, answerable, no-answer


@pytest.fixture(scope="module")
def evaluation():
    return Evaluation()


@pytest.fixture(scope="module")
def model():
    return dataset.vectors()["model"]


@pytest.mark.parametrize("split", dataset.SPLITS)
def test_the_committed_vectors_match_the_current_texts(split):
    assert dataset.vectors(split)["fingerprint"] == dataset.fingerprint(split), (
        "The evaluation texts changed since they were embedded. Run: "
        "docker compose exec backend python manage.py embed_rag_eval"
    )


def test_the_locked_test_set_is_unchanged():
    assert dataset.content_digest("test") == LOCKED_TEST_SET, (
        "The locked test set changed. It must stay as written before tuning; change it only "
        "on purpose, before any result on it has been seen."
    )


@pytest.mark.parametrize("split", dataset.SPLITS)
def test_the_dataset_is_well_formed(split):
    rows, answerable, no_answer = MINIMUM_SIZE[split]
    ids = {row["id"] for row in dataset.corpus(split)}
    questions = dataset.questions(split)
    assert len(ids) == len(dataset.corpus(split)) >= rows
    assert all(set(q["relevant"]) <= ids for q in questions)
    assert {q["type"] for q in questions} == set(TYPES)
    assert all(bool(q["relevant"]) == (q["type"] in ANSWERABLE) for q in questions)
    assert sum(1 for q in questions if q["relevant"]) >= answerable
    assert sum(1 for q in questions if not q["relevant"]) >= no_answer


@pytest.mark.parametrize("split", dataset.SPLITS)
def test_dated_questions_search_the_period_they_name(split):
    for question in dataset.questions(split):
        detected = detect_period(question["question"], TODAY)
        assert (detected is not None) == (question["type"] == "dated"), question["id"]


def test_report_every_configuration(evaluation, model):
    """Prints the comparison table (-s). The gates are the tests below."""
    tuned = profile_for(model)
    print(f"\nRetrieval on {len(dataset.corpus())} rows, {len(dataset.questions())} questions")
    print(
        f"  {'variant':9} {'mode':7} {'profile':8} {'recall@5':>9} {'MRR':>6} {'set F1':>7} "
        f"{'exact total':>12} {'no-match':>9}"
    )
    for variant in dataset.VARIANTS:
        for mode in MODES:
            for label, profile in (("untuned", UNTUNED), ("tuned", tuned)):
                result = evaluation.run(variant, profile, mode)
                print(
                    f"  {variant:9} {mode:7} {label:8} {result.recall_at_5:9.3f} "
                    f"{result.mrr:6.3f} {result.set_f1:7.3f} {result.exact_total:12.3f} "
                    f"{result.no_match:9.3f}"
                )


def test_production_search_keeps_its_baseline(evaluation, model):
    profile = profile_for(model)
    assert profile.tuned, f"{base_name(model)} has no tuned profile"
    result = evaluation.run(production_variant(profile), profile)
    for name, floor in BASELINE.items():
        assert getattr(result, name) >= floor, (name, result)


def test_cross_validation_scores_every_question_once(evaluation, model):
    profile = profile_for(model)
    validated = evaluation.cross_validate(production_variant(profile), profile)
    assert len(validated.picks) == FOLDS
    assert [o.question for o in validated.metrics.outcomes] == [q.id for q in evaluation.questions]


def test_hybrid_beats_either_side_alone(evaluation, model):
    profile = profile_for(model)
    variant = production_variant(profile)
    hybrid = evaluation.run(variant, profile, "hybrid")
    for mode in ("bm25", "vector"):
        assert hybrid.score >= evaluation.run(variant, profile, mode).score, mode


def test_the_profile_threshold_is_within_the_window_of_what_tuning_picks(evaluation, model):
    """Re-runs the tuning. Tuning already treats thresholds within ±WINDOW as equivalent, so a
    pick that moves inside that window is noise, and the shipped threshold stays. A pick that
    moves further means the data or the ranking changed: re-tune on purpose rather than drift."""
    profile = profile_for(model)
    threshold, result = evaluation.tune(production_variant(profile), profile)
    assert abs(profile.min_similarity - threshold) <= WINDOW + 1e-9, (
        f"Tuning now picks {threshold} ({result}); update the profile and BASELINE."
    )


def test_prefixes_are_kept_only_because_they_help(evaluation, model):
    profile = profile_for(model)
    if not (profile.doc_prefix or profile.query_prefix):
        pytest.skip("this profile uses plain text")
    plain = evaluation.tune("plain", profile)[1]
    prefixed = evaluation.tune("prefixed", profile)[1]
    assert prefixed.score >= plain.score, (plain, prefixed)

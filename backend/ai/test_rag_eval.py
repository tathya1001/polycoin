"""Retrieval quality on the committed evaluation set: CI's quality gate. Needs no model.

The vectors were made by a real embedding model (python manage.py embed_rag_eval), and the
ranking is the production code, so a change that makes search worse fails here. The table of
every configuration prints with:

    docker compose exec backend pytest ai/test_rag_eval.py -s
"""

import pytest

from ai.eval import dataset
from ai.eval.build_dataset import TODAY
from ai.eval.evaluate import MODES, Evaluation, Metrics
from ai.rag.periods import detect_period
from ai.rag.profiles import UNTUNED, base_name, profile_for

# The production configuration's scores when it was tuned (see the nomic profile). Improvements
# pass; a drop fails. Recorded rounded down, so float noise can't fail an unchanged ranking.
BASELINE = Metrics(recall_at_5=0.872, mrr=0.875, no_match=1.0)
DATED = {"gym-march", "power-last-month", "salary-this-year", "fuel-3-months", "rent-2025"}


@pytest.fixture(scope="module")
def evaluation():
    return Evaluation()


@pytest.fixture(scope="module")
def model():
    return dataset.vectors()["model"]


def production_variant(profile) -> str:
    return "prefixed" if profile.doc_prefix or profile.query_prefix else "plain"


def test_the_committed_vectors_match_the_current_texts():
    assert dataset.vectors()["fingerprint"] == dataset.fingerprint(), (
        "The evaluation texts changed since they were embedded. Run: "
        "docker compose exec backend python manage.py embed_rag_eval"
    )


def test_the_dataset_is_well_formed():
    ids = {row["id"] for row in dataset.corpus()}
    questions = dataset.questions()
    assert len(ids) == len(dataset.corpus()) >= 200
    assert all(set(q["relevant"]) <= ids for q in questions)
    assert sum(1 for q in questions if q["relevant"]) >= 30
    assert sum(1 for q in questions if not q["relevant"]) >= 8


def test_dated_questions_search_the_period_they_name():
    for question in dataset.questions():
        detected = detect_period(question["question"], TODAY)
        assert (detected is not None) == (question["id"] in DATED), question["id"]


def test_report_every_configuration(evaluation, model):
    """Prints the comparison table (-s). The gates are the tests below."""
    tuned = profile_for(model)
    print(f"\nRetrieval on {len(dataset.corpus())} rows, {len(dataset.questions())} questions")
    print(f"  {'variant':9} {'mode':7} {'profile':8} {'recall@5':>9} {'MRR':>6} {'no-match':>9}")
    for variant in dataset.VARIANTS:
        for mode in MODES:
            for label, profile in (("untuned", UNTUNED), ("tuned", tuned)):
                result = evaluation.run(variant, profile, mode)
                print(
                    f"  {variant:9} {mode:7} {label:8} {result.recall_at_5:9.3f} "
                    f"{result.mrr:6.3f} {result.no_match:9.3f}"
                )


def test_production_search_keeps_its_baseline(evaluation, model):
    profile = profile_for(model)
    assert profile.tuned, f"{base_name(model)} has no tuned profile"
    result = evaluation.run(production_variant(profile), profile)
    assert result.recall_at_5 >= BASELINE.recall_at_5, result
    assert result.mrr >= BASELINE.mrr, result
    assert result.no_match >= BASELINE.no_match, result


def test_hybrid_beats_either_side_alone(evaluation, model):
    profile = profile_for(model)
    variant = production_variant(profile)
    hybrid = evaluation.run(variant, profile, "hybrid")
    for mode in ("bm25", "vector"):
        assert hybrid.score >= evaluation.run(variant, profile, mode).score, mode


def test_the_profile_threshold_is_what_tuning_picks(evaluation, model):
    """Re-runs the tuning. If the data or the ranking changed, the recorded threshold must be
    re-tuned on purpose rather than drift."""
    profile = profile_for(model)
    threshold, result = evaluation.tune(production_variant(profile), profile)
    assert profile.min_similarity == threshold, (
        f"Tuning now picks {threshold} ({result}); update the profile and BASELINE."
    )


def test_prefixes_are_kept_only_because_they_help(evaluation, model):
    profile = profile_for(model)
    if not (profile.doc_prefix or profile.query_prefix):
        pytest.skip("this profile uses plain text")
    plain = evaluation.tune("plain", profile)[1]
    prefixed = evaluation.tune("prefixed", profile)[1]
    assert prefixed.score >= plain.score, (plain, prefixed)

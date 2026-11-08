"""The embedding model benchmark: per-model grids, candidate prefixes, the comparison, timing.

The end-to-end test scores the committed vectors (the suggested model) the way the benchmark
scores every candidate, so it also checks that the benchmark and the shipped profile agree.
"""

import json
from dataclasses import asdict
from io import StringIO

import pytest
from django.core.management import CommandError, call_command

from ai.eval import benchmark, candidates, dataset, embed
from ai.eval.evaluate import WINDOW, Evaluation, Outcome
from ai.rag.profiles import profile_for


@pytest.fixture(scope="module")
def committed_model():
    return dataset.vectors("dev")["model"]


# --- thresholds tried per model ------------------------------------------------------------------


def test_the_grid_spans_the_models_own_range_in_small_steps():
    evaluation = Evaluation()
    grid = evaluation.own_grid("prefixed")
    steps = {round(b - a, 3) for a, b in zip(grid, grid[1:])}
    assert steps == {0.005}
    assert 0 < grid[0] < profile_for(dataset.vectors()["model"]).min_similarity < grid[-1] <= 1


def test_the_grid_uses_no_relevance_labels():
    evaluation = Evaluation()
    before = evaluation.own_grid("prefixed")
    evaluation.questions = [
        q.__class__(q.id, q.kind, q.candidates, q.keyword, frozenset(), q.index)
        for q in evaluation.questions
    ]
    assert evaluation.own_grid("prefixed") == before


# --- candidates ----------------------------------------------------------------------------------


def test_a_model_with_a_profile_uses_the_profiles_prefixes(committed_model):
    profile = profile_for(committed_model)
    assert candidates.prefixes_for(committed_model) == (profile.doc_prefix, profile.query_prefix)


def test_an_unknown_model_must_be_added_before_it_is_compared():
    with pytest.raises(ValueError, match="PREFIXES"):
        candidates.prefixes_for("someone/new-embedder:latest")


def test_cache_files_are_named_by_base_name_and_split():
    assert candidates.cache_path("bge-m3:latest", "dev").name == "bge-m3-dev.json"
    assert candidates.cache_path("Some/Model:v2", "test").name == "some-model-test.json"


# --- the comparison ------------------------------------------------------------------------------


def _model_run(name: str, exact: list[bool]) -> dict:
    outcomes = [
        Outcome(
            f"q{n}",
            "exact",
            answerable=True,
            empty=False,
            f1=1.0 if right else 0.4,
            exact_total=right,
        )  # fmt: skip
        for n, right in enumerate(exact)
    ]
    return {"model": name, "outcomes": [asdict(o) for o in outcomes]}


def test_a_model_right_on_every_question_the_reference_missed_is_a_real_gain():
    reference = _model_run("ref", [False] * 8)
    better = _model_run("new", [True] * 8)
    result = benchmark.compare_to(reference, better)
    assert result["real"] and result["overall"][0] == pytest.approx(0.6)
    assert result["mcnemar_p"] == pytest.approx(2 / 2**8)


def test_a_model_that_wins_some_and_loses_some_could_be_noise():
    reference = _model_run("ref", [True, False] * 4)
    other = _model_run("new", [False, True] * 4)
    assert not benchmark.compare_to(reference, other)["real"]


def test_the_benchmark_scores_the_committed_model_as_its_profile_says(committed_model, monkeypatch):
    """Run on the committed vectors, the benchmark keeps the profile's prefixes and lands within
    the tuning window of the shipped threshold."""
    monkeypatch.setattr(candidates, "cache_path", lambda model, split: dataset.vectors_path(split))
    run = benchmark.build([committed_model], reference=committed_model)
    (scored,) = run["models"]
    profile = profile_for(committed_model)
    assert scored["variant"] == ("prefixed" if profile.doc_prefix else "plain")
    assert abs(scored["threshold"] - profile.min_similarity) <= WINDOW + 1e-9
    assert scored["versus_reference"] is None
    held = scored["cross_validated"]
    assert 0 < held["overall"] <= 1
    assert scored["intervals"]["overall"][1] <= held["overall"] <= scored["intervals"]["overall"][2]
    assert len(scored["outcomes"]) == len(dataset.questions("dev"))
    assert "overall" in benchmark.format_models(run)


# --- speed and the command -----------------------------------------------------------------------


def test_the_cosine_timing_is_a_positive_number_of_milliseconds():
    assert benchmark.cosine_ms(64, rows=500, repeats=3) > 0


@pytest.mark.parametrize(
    "content, expected", [("10000 100000\n", 0.1), ("max 100000\n", None), (None, None)]
)
def test_the_cpu_limit_is_read_from_the_cgroup(tmp_path, monkeypatch, content, expected):
    path = tmp_path / "cpu.max"
    if content is not None:
        path.write_text(content)
    monkeypatch.setattr(benchmark, "CPU_MAX", str(path))
    assert benchmark.cpu_limit() == expected


def test_a_tag_listed_twice_records_the_same_digest_every_time(monkeypatch):
    tags = [
        {"name": "embedder:latest", "digest": "82f0", "size": 2},
        {"name": "other:latest", "digest": "0000", "size": 3},
        {"name": "embedder:latest", "digest": "3a2d", "size": 1},
    ]
    for listing in (tags, list(reversed(tags))):
        monkeypatch.setattr(embed, "_call", lambda base, path, body=None: {"models": listing})
        assert embed.model_info("http://x", "embedder:latest") == {
            "digest": "3a2d",
            "size": 1,
            "duplicates": 2,
        }


def test_the_command_says_how_to_cache_a_model_first(tmp_path, monkeypatch):
    monkeypatch.setattr(candidates, "CACHE", tmp_path / "empty")
    with pytest.raises(CommandError, match="embed_rag_eval --cache"):
        call_command("rag_models", stdout=StringIO())


def test_cached_models_are_read_from_the_cache_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(candidates, "CACHE", tmp_path)
    for model in ("b-model:latest", "a-model:latest"):
        (tmp_path / f"{model.split(':')[0]}-dev.json").write_text(json.dumps({"model": model}))
    (tmp_path / "a-model-test.json").write_text(json.dumps({"model": "ignored"}))
    assert candidates.cached_models() == ["a-model:latest", "b-model:latest"]

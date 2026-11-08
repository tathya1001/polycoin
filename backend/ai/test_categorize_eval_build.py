"""The categorisation evaluation input: how it is built, and (opt-in) building it for real.

Building runs here, on the test database, because it needs a throwaway user with every migration
applied; nothing is ever written to a real database. Opt-in, with a local Ollama:

    docker compose exec -e CATEGORIZE_EVAL_BUILD=1 -e CATEGORIZE_EVAL_OUT=<path> \
        backend pytest ai/test_categorize_eval_build.py -k real -s

scripts/build-categorize-eval.sh runs that and moves the file where the frontend reads it.
CATEGORIZE_EVAL_MODEL picks the model (default embeddinggemma:latest); OLLAMA_URL its address.
"""

import json
import os
from pathlib import Path

import pytest

from ai.eval import categorize, dataset
from ai.eval.embed import DEFAULT_URL
from transactions.models import Transaction
from transactions.tests import make_user

pytestmark = pytest.mark.django_db


@pytest.fixture
def small_corpus(monkeypatch):
    """The first rows of each split, two folds and two example counts: quick, same code path."""
    rows = {split: dataset.corpus(split)[:24] for split in dataset.SPLITS}
    monkeypatch.setattr(dataset, "corpus", lambda split="dev": rows[split])
    monkeypatch.setattr(categorize, "FOLDS", 2)
    monkeypatch.setattr(categorize, "CURVE", (0, 2))
    return rows


def test_every_fold_and_example_count_gets_a_run(small_corpus, settings):
    runs = categorize.build_runs(make_user)
    dev = [(r["fold"], r["examples"]) for r in runs if r["split"] == "dev"]
    test = [(r["fold"], r["examples"]) for r in runs if r["split"] == "test"]
    assert dev == [(0, 0), (0, 2), (1, 0), (1, 2)]
    assert test == [
        (0, settings.AI_MAX_EXAMPLES_PER_CATEGORY),
        (1, settings.AI_MAX_EXAMPLES_PER_CATEGORY),
    ]


def test_the_targets_are_the_folds_rows_named_by_their_corpus_ids(small_corpus):
    for run in categorize.build_runs(make_user):
        targets = {t["transaction"] for t in run["run"]["targets"]}
        assert targets == set(run["truth"])
        corpus_ids = {row["id"] for row in small_corpus[run["split"]]}
        assert targets <= corpus_ids


def test_both_folds_together_cover_every_row_once(small_corpus):
    dev = [
        r for r in categorize.build_runs(make_user) if r["split"] == "dev" and r["examples"] == 0
    ]
    seen = [row for run in dev for row in run["truth"]]
    assert sorted(seen) == sorted(row["id"] for row in small_corpus["dev"])


def test_candidates_are_named_and_examples_never_include_the_default_category(small_corpus):
    run = next(r for r in categorize.build_runs(make_user) if r["examples"] == 2)
    names = {c["category"] for cands in run["run"]["candidates"].values() for c in cands}
    assert names and "Others" not in names
    assert all(
        c["category"] == c["name"] for cands in run["run"]["candidates"].values() for c in cands
    )


def test_with_no_examples_every_category_is_represented_by_its_label_only(small_corpus):
    run = next(r for r in categorize.build_runs(make_user) if r["examples"] == 0)
    assert all(not c["examples"] for cands in run["run"]["candidates"].values() for c in cands)


def test_nothing_stays_in_the_database(small_corpus):
    categorize.build_runs(make_user)
    assert not Transaction.objects.exists()


@pytest.mark.skipif(
    not os.environ.get("CATEGORIZE_EVAL_BUILD"), reason="set CATEGORIZE_EVAL_BUILD=1 (needs Ollama)"
)
def test_real_build_writes_the_evaluation_input():
    model = os.environ.get("CATEGORIZE_EVAL_MODEL", "embeddinggemma:latest")
    data = categorize.build(make_user, os.environ.get("OLLAMA_URL", DEFAULT_URL), model)
    output = Path(os.environ["CATEGORIZE_EVAL_OUT"])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"\n{len(data['runs'])} runs, {len(data['vectors'])} texts embedded with {model}")

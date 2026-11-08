"""The evaluation report and its command, on small hand-made runs: no model, no real search."""

from dataclasses import asdict
from io import StringIO

import pytest
from django.core.management import CommandError, call_command

from ai.eval import report, results, search_report
from ai.eval.evaluate import MODES, Metrics, Outcome


def _run(label: str, fingerprint: str = "same", exact=(True, False), split: str = "dev") -> dict:
    """A saved-run-shaped dict: two answerable questions and one with no answer."""
    outcomes = [
        Outcome(
            f"q{n}",
            "exact",
            answerable=True,
            empty=False,
            f1=1.0 if right else 0.5,
            recall_at_5=1.0,
            exact_total=right,
        )  # fmt: skip
        for n, right in enumerate(exact)
    ] + [Outcome("none", "no-answer", answerable=False, empty=True)]
    metrics = Metrics.of(outcomes)
    production = {
        **metrics.as_dict(),
        "intervals": {name: metrics.interval(name).as_list() for name in search_report.INTERVALS},
    }
    return {
        "kind": "search",
        "label": label,
        "meta": {
            "date": "2026-11-06",
            "commit": "abc1234",
            "split": split,
            "model": "embedder:latest",
            "digest": "0123456789abcdef",
            "fingerprint": fingerprint,
            "rows": 10,
            "questions": 3,
            "answerable": 2,
            "settings": {"variant": "prefixed", "min_similarity": 0.52, "rrf_k": 60},
        },
        "production": production,
        "cross_validated": {"picks": [0.52, 0.525], **metrics.as_dict()}
        if split == "dev"
        else None,
        "modes": {mode: metrics.as_dict() for mode in MODES},
        "by_type": {
            "exact": Metrics.of(outcomes[:-1]).as_dict(),
            "no-answer": Metrics.of(outcomes[-1:]).as_dict(),
        },
        "outcomes": [asdict(o) for o in outcomes],
    }


def test_the_report_shows_the_production_numbers_with_intervals_and_folds():
    page = report.render(_run("now"), [], {})
    assert page.startswith("# AI evaluation report")
    assert "## Search" in page and "| Overall (every question once) | 0.833 |" in page
    assert (
        "Cross-validated: each fold scored by the threshold tuned without it (0.520, 0.525)" in page
    )
    assert "### Each search side alone" in page and "| hybrid |" in page


def test_no_answer_types_show_only_the_numbers_that_mean_something():
    page = report.render(_run("now"), [], {})
    no_answer_row = next(line for line in page.splitlines() if line.startswith("| no-answer |"))
    assert no_answer_row == "| no-answer | 1 | 1.000 | – | – | – | 1.000 |"


def test_kinds_with_no_saved_runs_say_so():
    page = report.render(_run("now"), [], {})
    for _, title in report.SAVED_SECTIONS:
        assert f"## {title}\n\n_Not run yet._" in page


def test_saved_runs_of_other_kinds_show_their_headline_numbers():
    runs = [
        {"label": "first", "meta": {"date": "2026-11-07", "commit": "a1"}, "headline": {"x": 0.5}},
        {"label": "second", "meta": {"date": "2026-11-08", "commit": "b2"},
         "headline": {"x": 0.75, "y": 3}},
    ]  # fmt: skip
    page = report.render(_run("now"), [], {"answers": runs})
    assert "| Run | Date | Commit | x | y |" in page
    assert "| first | 2026-11-07 | `a1` | 0.500 | – |" in page
    assert "| second | 2026-11-08 | `b2` | 0.750 | 3 |" in page


def test_the_history_table_marks_numbers_an_older_run_never_measured():
    old = _run("baseline")
    del old["production"]["overall"]
    page = report.render(_run("now"), [old], {})
    row = next(line for line in page.splitlines() if line.startswith("| baseline |"))
    assert "| 0.520 | – |" in row


def test_a_comparison_on_the_same_dataset_reads_its_paired_tests():
    before, after = _run("before", exact=(False, False)), _run("after", exact=(True, True))
    page = report.render(after, [], {}, ("before", search_report.compare_data(before, after)))
    assert "### Before and after (before: saved run `before`)" in page
    assert "- Exact totals: 2 fixed, 0 broken" in page
    assert "| Set F1 | 0.500 | 1.000 | +0.500 |" in page


def test_an_unchanged_run_reads_as_no_change():
    run = _run("same")
    page = report.render(run, [], {}, ("same", search_report.compare_data(run, run)))
    assert "- Set F1: no change" in page


def test_a_comparison_across_datasets_says_why_there_is_no_paired_test():
    data = search_report.compare_data(_run("old", "one"), _run("new", "two"))
    page = report.render(_run("new", "two"), [], {}, ("old", data))
    assert "Different datasets, so no paired test." in page


def test_the_locked_test_set_appears_only_when_scored():
    assert "Held-out results" not in report.render(_run("now"), [], {})
    page = report.render(_run("now"), [], {}, final=_run("final", split="test"))
    assert "### Held-out results: the locked test set" in page


# --- saved runs ----------------------------------------------------------------------------------


@pytest.fixture
def saved_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(results, "RESULTS", tmp_path)
    return tmp_path


def test_load_all_lists_saved_runs_oldest_first(saved_runs):
    results.save("search", "second", {"meta": {"date": "2026-11-06"}})
    (saved_runs / "search-first.json").write_text(
        '{"kind": "search", "label": "first", "meta": {"date": "2026-11-01"}}', encoding="utf-8"
    )
    results.save("answers", "other", {"meta": {"date": "2026-11-06"}})
    assert [run["label"] for run in results.load_all("search")] == ["first", "second"]


def test_load_all_with_nothing_saved_is_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(results, "RESULTS", tmp_path / "missing")
    assert results.load_all("search") == []


# --- the command ---------------------------------------------------------------------------------


@pytest.fixture
def fake_search(monkeypatch):
    """The command with a hand-made run instead of a real search over the evaluation set."""
    monkeypatch.setattr(search_report, "build", lambda evaluation=None: _run("now"))


def test_the_command_prints_the_report(saved_runs, fake_search):
    out = StringIO()
    call_command("ai_eval_report", stdout=out)
    assert out.getvalue().startswith("# AI evaluation report")


def test_the_command_compares_with_a_saved_run(saved_runs, fake_search):
    results.save("search", "before", _run("before", exact=(False, False)))
    out = StringIO()
    call_command("ai_eval_report", "--compare", "before", stdout=out)
    assert "Exact totals: 1 fixed, 0 broken" in out.getvalue()


def test_the_command_refuses_a_run_that_was_never_saved(saved_runs, fake_search):
    with pytest.raises(CommandError, match="--record nowhere"):
        call_command("ai_eval_report", "--compare", "nowhere", stdout=StringIO())

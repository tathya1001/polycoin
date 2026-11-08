"""One search evaluation run for the production settings: build it, print it, compare two runs.

A run holds the production metrics with confidence intervals, honest cross-validated scores, each
search side alone, scores per question type and every question's outcome. The outcomes make a
paired comparison possible: a later run on the same dataset is compared question by question.
"""

from dataclasses import asdict

from django.conf import settings

from ai.rag.profiles import PROMPT_VERSION, TEXT_VERSION, profile_for

from . import dataset, results, stats
from .evaluate import MODES, Evaluation, Metrics, production_variant

KIND = "search"
INTERVALS = ("overall", "recall_at_5", "set_f1", "exact_total")
HEADLINE = ("overall", "set_f1", "exact_total", "recall_at_5", "no_match")
# Paired checks: per-question numbers get a paired bootstrap; yes/no ones an exact McNemar test.
PAIRED = (("set_f1", "f1"), ("recall_at_5", "recall_at_5"))
COLUMNS = (
    ("recall@5", "recall_at_5"),
    ("MRR", "mrr"),
    ("in prompt", "recall_in_prompt"),
    ("set P", "set_precision"),
    ("set R", "set_recall"),
    ("set F1", "set_f1"),
    ("exact total", "exact_total"),
    ("no-match", "no_match"),
    ("overall", "overall"),
)


def build(evaluation: Evaluation | None = None) -> dict:
    """The production settings scored on the evaluation's split. The locked test set is never
    cross-validated: that would tune on it."""
    evaluation = evaluation or Evaluation()
    vectors = dataset.vectors(evaluation.split)
    profile = profile_for(vectors["model"])
    variant = production_variant(profile)
    production = evaluation.run(variant, profile)
    validated = evaluation.cross_validate(variant, profile) if evaluation.split == "dev" else None
    kinds = sorted({o.kind for o in production.outcomes})
    return {
        "meta": results.metadata(
            split=evaluation.split,
            model=vectors["model"],
            digest=vectors["digest"],
            dims=vectors["dims"],
            fingerprint=vectors["fingerprint"],
            text_version=TEXT_VERSION,
            prompt_version=PROMPT_VERSION,
            rows=len(evaluation.rows),
            questions=len(evaluation.questions),
            answerable=sum(1 for q in evaluation.questions if q.relevant),
            settings={
                "variant": variant,
                "min_similarity": profile.min_similarity,
                "rrf_k": settings.RAG_RRF_K,
                "max_matches": settings.RAG_MAX_MATCHES,
                "top_k": settings.RAG_TOP_K,
            },
        ),
        "production": {
            **production.as_dict(),
            "intervals": {name: production.interval(name).as_list() for name in INTERVALS},
        },
        "cross_validated": (
            {"picks": validated.picks, **validated.metrics.as_dict()} if validated else None
        ),
        "modes": {mode: evaluation.run(variant, profile, mode).as_dict() for mode in MODES},
        "by_type": {
            kind: Metrics.of([o for o in production.outcomes if o.kind == kind]).as_dict()
            for kind in kinds
        },
        "outcomes": [asdict(o) for o in production.outcomes],
    }


def _row(label: str, numbers: dict) -> str:
    return f"  {label:<24}" + "".join(f"{numbers[key]:>12.3f}" for _, key in COLUMNS)


def _header() -> str:
    return f"  {'':<24}" + "".join(f"{title:>12}" for title, _ in COLUMNS)


def format_run(run: dict) -> str:
    meta, production, validated = run["meta"], run["production"], run["cross_validated"]
    lines = [
        f"Search on the {meta.get('split', 'dev')} set: {meta['rows']} rows, "
        f"{meta['questions']} questions ({meta['answerable']} answerable); {meta['model']}, "
        f"{meta['settings']['variant']}, threshold {meta['settings']['min_similarity']} "
        f"(commit {meta['commit']}, {meta['date']})",
        _header(),
        _row("production", production),
    ]
    if validated:
        picks = " ".join(f"{p:.3f}" for p in validated["picks"])
        lines += [_row("cross-validated", validated), f"  {'':<24}thresholds per fold: {picks}"]
    for name, (mean, low, high) in production["intervals"].items():
        lines.append(f"  {'95% CI ' + name:<24}{mean:.3f}  [{low:.3f}, {high:.3f}]")
    lines += ["", "  Each side alone (production variant and threshold):", _header()]
    lines += [_row(mode, numbers) for mode, numbers in run["modes"].items()]
    lines += ["", "  By question type:", _header()]
    for kind, numbers in run["by_type"].items():
        count = sum(1 for o in run["outcomes"] if o["kind"] == kind)
        if all(not o["answerable"] for o in run["outcomes"] if o["kind"] == kind):
            # Only no-match (and so overall) means anything for questions with no answer.
            shown = {"no_match", "overall"}
            cells = "".join(
                f"{numbers[key]:>12.3f}" if key in shown else " " * 12 for _, key in COLUMNS
            )
            lines.append(f"  {f'{kind} ({count})':<24}{cells}")
        else:
            lines.append(_row(f"{kind} ({count})", numbers))
    wrong = [o["question"] for o in run["outcomes"] if o["answerable"] and not o["exact_total"]]
    missed = [o["question"] for o in run["outcomes"] if not o["answerable"] and not o["empty"]]
    lines += ["", f"  Wrong totals ({len(wrong)}): {', '.join(wrong) or 'none'}"]
    lines.append(
        f"  No-answer questions that found rows ({len(missed)}): {', '.join(missed) or 'none'}"
    )
    return "\n".join(lines)


def headline(run: dict) -> dict:
    """The few numbers a history table shows for a run. Runs saved before a metric existed
    lack it: None."""
    return {key: run["production"].get(key) for key in HEADLINE}


def _overall_of(outcome: dict) -> float:
    return outcome["f1"] if outcome["answerable"] else float(outcome["empty"])


def compare_data(before: dict, after: dict) -> dict:
    """Before, after and change for every column; when both runs scored the same dataset, also
    paired intervals of the per-question changes and an exact McNemar test on exact totals."""
    rows = [
        (key, title, before["production"].get(key), after["production"].get(key))
        for title, key in COLUMNS
    ]
    result = {"rows": rows, "paired": None}
    if before["meta"]["fingerprint"] != after["meta"]["fingerprint"]:
        return result

    old = {o["question"]: o for o in before["outcomes"]}
    new = {o["question"]: o for o in after["outcomes"]}
    answerable = [q for q in old if old[q]["answerable"]]
    changes = {
        "overall": stats.paired_bootstrap(
            [_overall_of(old[q]) for q in old], [_overall_of(new[q]) for q in old]
        )
    }
    for name, field in PAIRED:
        changes[name] = stats.paired_bootstrap(
            [old[q][field] for q in answerable], [new[q][field] for q in answerable]
        )
    result["paired"] = {
        "changes": changes,
        "mcnemar_p": stats.mcnemar_exact(
            [old[q]["exact_total"] for q in answerable], [new[q]["exact_total"] for q in answerable]
        ),
        "fixed": [q for q in answerable if new[q]["exact_total"] and not old[q]["exact_total"]],
        "broken": [q for q in answerable if old[q]["exact_total"] and not new[q]["exact_total"]],
    }
    return result


def _number(value, sign: bool = False) -> str:
    if value is None:
        return "–"
    return f"{value:+.3f}" if sign else f"{value:.3f}"


def compare(before: dict, after: dict) -> str:
    """The comparison as text for the terminal."""
    data = compare_data(before, after)
    lines = [f"  {'':<24}{'before':>10}{'after':>10}{'change':>10}"]
    for _, title, old, new in data["rows"]:
        change = new - old if old is not None and new is not None else None
        lines.append(
            f"  {title:<24}{_number(old):>10}{_number(new):>10}{_number(change, sign=True):>10}"
        )
    paired = data["paired"]
    if paired is None:
        lines.append("  Different datasets, so no paired test: compare the cross-validated rows.")
        return "\n".join(lines)
    lines.append("")
    for name, change in paired["changes"].items():
        verdict = "real" if change.excludes_zero() else "could be noise"
        lines.append(
            f"  {name} change {change.mean:+.3f}, 95% CI [{change.low:+.3f}, {change.high:+.3f}]: "
            f"{verdict}"
        )
    lines.append(
        f"  exact total: fixed {len(paired['fixed'])}, broken {len(paired['broken'])}, "
        f"McNemar p = {paired['mcnemar_p']:.3f}"
    )
    if paired["fixed"]:
        lines.append(f"    fixed: {', '.join(paired['fixed'])}")
    if paired["broken"]:
        lines.append(f"    broken: {', '.join(paired['broken'])}")
    return "\n".join(lines)

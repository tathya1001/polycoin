"""The AI evaluation report: one markdown page from the live search scores and every saved run.

`python manage.py ai_eval_report` prints it; scripts/ai-eval.sh writes it to a private file. Search
is scored live, because it needs no model. Runs that do need one (answers, the panel builder) and
the categorisation and performance runs are read from their saved results, so building the report
never needs Ollama.

Every saved run has "meta" (what produced it) and, for kinds other than search, "headline": the
few numbers its history table shows.
"""

from . import search_report

# Kinds rendered from saved runs only, in report order.
SAVED_SECTIONS = (
    ("models", "Embedding models"),
    ("cosine", "Server cosine time by vector size"),
    ("categorization", "Categorisation"),
    ("answers", "Answers"),
    ("agent", "Panel builder"),
    ("performance", "Performance"),
    ("judge", "LLM judge agreement with the labels"),
)
METRIC_NAMES = {
    "overall": "Overall (every question once)",
    "set_f1": "Set F1",
    "exact_total": "Exact ₹ total",
    "recall_at_5": "Recall@5",
    "mrr": "MRR",
    "recall_in_prompt": "Recall in prompt (top 20)",
    "set_precision": "Set precision",
    "set_recall": "Set recall",
    "no_match": "No-match",
}
SHORT = ("overall", "set_f1", "exact_total", "recall_at_5", "no_match")


def _n(value) -> str:
    if value is None:
        return "–"
    if isinstance(value, float):  # scores to 3 places; speeds, sizes and times to 1
        return f"{value:.3f}" if abs(value) <= 1.5 else f"{value:.1f}"
    return str(value)


def _table(header: list[str], rows: list[list]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(_n(cell) for cell in row) + " |" for row in rows]
    return lines + [""]


def _verdict(change) -> str:
    """How to read a paired change: its interval decides, not its size."""
    if change.low == change.high == 0:
        return "no change"
    kind = "a real change" if change.excludes_zero() else "could be noise"
    return f"{change.mean:+.3f} ({kind})"


def _setup(run: dict) -> str:
    meta, settings = run["meta"], run["meta"]["settings"]
    return (
        f"{meta['rows']} rows, {meta['questions']} questions ({meta['answerable']} answerable). "
        f"Model `{meta['model']}` (digest {meta['digest'][:12]}), {settings['variant']}, "
        f"threshold {settings['min_similarity']}, RRF k {settings['rrf_k']}. "
        f"Commit `{meta['commit']}`, {meta['date']}."
    )


def _by_type(run: dict) -> list[str]:
    rows = []
    for kind, numbers in run["by_type"].items():
        outcomes = [o for o in run["outcomes"] if o["kind"] == kind]
        answerable = any(o["answerable"] for o in outcomes)
        rows.append(
            [kind, len(outcomes)]
            + [
                numbers[key] if answerable or key in ("no_match", "overall") else None
                for key in SHORT
            ]  # fmt: skip
        )
    return _table(["Type", "Questions"] + [METRIC_NAMES[key] for key in SHORT], rows)


def _search(current: dict, history: list[dict], comparison, final: dict | None) -> list[str]:
    production, validated = current["production"], current["cross_validated"]
    lines = ["## Search", "", f"Dev set: {_setup(current)}", "", "### Production settings", ""]
    rows = []
    for key, name in METRIC_NAMES.items():
        interval = production["intervals"].get(key)
        ci = f"{interval[1]:.3f}–{interval[2]:.3f}" if interval else None
        rows.append([name, production[key], ci, validated[key] if validated else None])
    lines += _table(["Metric", "Value", "95% CI", "Cross-validated"], rows)
    if validated:
        picks = ", ".join(f"{p:.3f}" for p in validated["picks"])
        lines += [
            f"Cross-validated: each fold scored by the threshold tuned without it ({picks}).",
            "",
        ]

    lines += ["### Each search side alone", ""]
    lines += _table(
        ["Side"] + [METRIC_NAMES[key] for key in SHORT],
        [[mode] + [numbers[key] for key in SHORT] for mode, numbers in current["modes"].items()],
    )
    lines += ["### By question type", ""] + _by_type(current)

    if comparison:
        label, data = comparison
        lines += [f"### Before and after (before: saved run `{label}`)", ""]
        lines += _table(
            ["Metric", "Before", "After", "Change"],
            [
                [
                    METRIC_NAMES[key],
                    old,
                    new,
                    f"{new - old:+.3f}" if None not in (old, new) else None,
                ]
                for key, _, old, new in data["rows"]
            ],  # fmt: skip
        )
        paired = data["paired"]
        if paired is None:
            lines += ["Different datasets, so no paired test.", ""]
        else:
            for name, change in paired["changes"].items():
                lines.append(
                    f"- {METRIC_NAMES.get(name, name)}: {_verdict(change)}, 95% CI "
                    f"{change.low:+.3f} to {change.high:+.3f}."
                )
            lines.append(
                f"- Exact totals: {len(paired['fixed'])} fixed, {len(paired['broken'])} broken "
                f"(exact McNemar p = {paired['mcnemar_p']:.3f})."
            )
            lines.append("")

    if history:
        lines += ["### History of saved runs", ""]
        lines += _table(
            ["Run", "Date", "Commit", "Set", "Rows", "Questions", "Threshold"]
            + [METRIC_NAMES[key] for key in SHORT],
            [
                [
                    run["label"],
                    run["meta"]["date"],
                    f"`{run['meta']['commit']}`",
                    run["meta"].get("split", "dev"),
                    run["meta"]["rows"],
                    run["meta"]["questions"],
                    run["meta"]["settings"]["min_similarity"],
                ]
                + list(search_report.headline(run).values())
                for run in history
            ],  # fmt: skip
        )

    if final:
        lines += ["### Held-out results: the locked test set", "", f"Test set: {_setup(final)}", ""]
        lines += _table(
            ["Metric", "Value", "95% CI"],
            [
                [
                    name,
                    final["production"][key],
                    "–".join(f"{x:.3f}" for x in final["production"]["intervals"][key][1:])
                    if key in final["production"]["intervals"]
                    else None,
                ]
                for key, name in METRIC_NAMES.items()
            ],  # fmt: skip
        )
        lines += _by_type(final)
    return lines


def _models(run: dict) -> list[str]:
    """The latest model comparison: cross-validated quality, speed and size, and per type."""
    meta = run["meta"]
    lines = [
        f"Run `{run['label']}`, {meta['date']}, commit `{meta['commit']}`. Dev set, "
        f"{meta['questions']} questions; every model with its own prefixes and a threshold tuned "
        f"over its own score range; cross-validated. Compared question by question with "
        f"`{meta['reference']}`.",
        "",
    ]
    rows = []
    for m in run["models"]:
        held, (_, low, high) = m["cross_validated"], m["intervals"]["overall"]
        versus = m["versus_reference"]
        change = "reference"
        if versus:
            mean, v_low, v_high = versus["overall"]
            kind = "real" if versus["real"] else "could be noise"
            change = f"{mean:+.3f} ({v_low:+.3f} to {v_high:+.3f}, {kind})"
        rows.append(
            [f"`{m['model']}`", m["dims"], m["variant"], m["threshold"], held["overall"],
             f"{low:.3f}–{high:.3f}", change, held["set_f1"], held["exact_total"],
             held["recall_at_5"], m["docs_per_second"], m["model_mb"], m["index_mb_per_10k"]]
        )  # fmt: skip
    lines += _table(
        ["Model", "Dims", "Variant", "Threshold", "Overall", "95% CI", "Change vs reference",
         "Set F1", "Exact ₹ total", "Recall@5", "Docs/s", "Model MB", "Index MB per 10k rows"],
        rows,
    )  # fmt: skip
    kinds = list(run["models"][0]["by_type"])
    lines += ["Overall by question type:", ""]
    lines += _table(
        ["Model"] + kinds,
        [[f"`{m['model']}`"] + [m["by_type"][k]["overall"] for k in kinds] for m in run["models"]],
    )
    return lines


def _saved(kind: str, title: str, runs: list[dict]) -> list[str]:
    lines = [f"## {title}", ""]
    if not runs:
        return lines + ["_Not run yet._", ""]
    if kind == "models":
        return lines + _models(runs[-1])
    columns = list(dict.fromkeys(key for run in runs for key in run.get("headline", {})))
    return lines + _table(
        ["Run", "Date", "Commit"] + columns,
        [
            [run["label"], run["meta"]["date"], f"`{run['meta']['commit']}`"]
            + [run.get("headline", {}).get(key) for key in columns]
            for run in runs
        ],
    )


def render(
    current: dict,
    history: list[dict],
    saved: dict[str, list[dict]],
    comparison: tuple[str, dict] | None = None,
    final: dict | None = None,
) -> str:
    """The whole report. `current` is a fresh search run (search_report.build), `history` the
    saved search runs, `saved` the saved runs of every other kind, `comparison` (label,
    search_report.compare_data) and `final` a run on the locked test set."""
    lines = [
        "# AI evaluation report",
        "",
        f"Generated {current['meta']['date']} from commit `{current['meta']['commit']}`. "
        "Every number comes from the fictional evaluation sets in `backend/ai/eval/`.",
        "",
    ]
    lines += _search(current, history, comparison, final)
    for kind, title in SAVED_SECTIONS:
        lines += _saved(kind, title, saved.get(kind, []))
    return "\n".join(lines).rstrip() + "\n"

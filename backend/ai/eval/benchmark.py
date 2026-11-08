"""Compares embedding models on the dev set: quality, speed and size, with the production ranking.

Every model is scored the way the production model is: with its own task prefixes (and with plain
text, when it has prefixes), a threshold tuned over its own score range, and cross-validated
scores, so no model's numbers come from the questions that tuned it. Cross-validated overall picks
the variant. Each model is compared with the production model question by question.

Speed is measured where each cost falls: embedding on the dev machine's Ollama (as indexing runs
on the user's machine), and the server's exact cosine over RAG_MAX_DOCS rows (run that part in a
container limited like the server: see the rag_models command).
"""

import time
from dataclasses import asdict

import numpy as np
from django.conf import settings

from ai.rag.profiles import Profile, base_name
from ai.rag.retriever import cosine_scores

from . import candidates, dataset, results, stats
from .evaluate import Evaluation, Metrics, Outcome, overall_score, profile_with

KIND = "models"
COSINE_KIND = "cosine"
INTERVALS = ("overall", "set_f1", "exact_total")
CPU_MAX = "/sys/fs/cgroup/cpu.max"


def evaluate_model(model: str) -> dict:
    path = candidates.cache_path(model, "dev")
    vectors = dataset.load_vectors(path)
    if vectors["fingerprint"] != dataset.fingerprint("dev"):
        raise ValueError(f"{path.name} is stale. Run: embed_rag_eval --cache --model {model}")
    evaluation = Evaluation("dev", vectors=vectors)
    doc_prefix, query_prefix = candidates.prefixes_for(model)
    base = Profile(doc_prefix, query_prefix)
    tried = {}
    for variant in ("plain", "prefixed") if doc_prefix or query_prefix else ("plain",):
        grid = evaluation.own_grid(variant)
        threshold, tuned = evaluation.tune(variant, base, grid=grid)
        tried[variant] = (
            threshold,
            tuned,
            evaluation.cross_validate(variant, base, grid=grid),
            grid,
        )
    variant = max(tried, key=lambda v: tried[v][2].metrics.overall)
    threshold, tuned, validated, grid = tried[variant]
    held_out = validated.metrics
    timing = vectors["timing"] or {}
    seconds = timing.get("plain_seconds")
    return {
        "model": model,
        "digest": vectors["digest"],
        "dims": vectors["dims"],
        "model_mb": round(timing["model_bytes"] / 1e6) if "model_bytes" in timing else None,
        "docs_per_second": round(timing["documents"] / seconds, 1) if seconds else None,
        "index_mb_per_10k": round(vectors["dims"] * 2 * 10_000 / 1e6, 1),  # float16 vectors
        "variant": variant,
        "threshold": threshold,
        "grid": [grid[0], grid[-1]],
        "picks": validated.picks,
        "variants": {
            v: {"threshold": t[0], "cv_overall": round(t[2].metrics.overall, 4)}
            for v, t in tried.items()
        },
        "tuned": tuned.as_dict(),
        "cross_validated": held_out.as_dict(),
        "intervals": {name: held_out.interval(name).as_list() for name in INTERVALS},
        "vector_only": evaluation.run(variant, profile_with(base, threshold), "vector").as_dict(),
        "by_type": {
            kind: Metrics.of([o for o in held_out.outcomes if o.kind == kind]).as_dict()
            for kind in sorted({o.kind for o in held_out.outcomes})
        },
        "outcomes": [asdict(o) for o in held_out.outcomes],
    }


def compare_to(reference: dict, other: dict) -> dict:
    """`other` against `reference` on the same questions, both cross-validated: the paired change
    of overall, and an exact McNemar test on exact totals."""
    old = {o["question"]: Outcome(**o) for o in reference["outcomes"]}
    new = {o["question"]: Outcome(**o) for o in other["outcomes"]}
    change = stats.paired_bootstrap(
        [overall_score(old[q]) for q in old], [overall_score(new[q]) for q in old]
    )
    answerable = [q for q in old if old[q].answerable]
    p_value = stats.mcnemar_exact(
        [old[q].exact_total for q in answerable], [new[q].exact_total for q in answerable]
    )
    return {"overall": change.as_list(), "real": change.excludes_zero(), "mcnemar_p": p_value}


def build(models: list[str], reference: str) -> dict:
    """Every model's scores, each compared with `reference` (the production model)."""
    scored = [evaluate_model(model) for model in models]
    matches = [run for run in scored if base_name(run["model"]) == base_name(reference)]
    if not matches:
        raise ValueError(f"The reference model {reference} has no cached vectors.")
    for run in scored:
        run["versus_reference"] = None if run is matches[0] else compare_to(matches[0], run)
    return {
        "meta": results.metadata(
            reference=reference,
            fingerprint=dataset.fingerprint("dev"),
            questions=len(dataset.questions("dev")),
            rows=len(dataset.corpus("dev")),
        ),
        "models": scored,
    }


def cpu_limit() -> float | None:
    """The container's CPU quota (0.1 under `docker run --cpus 0.1`), or None for no limit."""
    try:
        with open(CPU_MAX) as file:
            quota, period = file.read().split()
    except (OSError, ValueError):
        return None
    return None if quota == "max" else int(quota) / int(period)


def cosine_ms(dims: int, rows: int | None = None, repeats: int = 7) -> float:
    """Median wall time, in milliseconds, of the server's exact cosine over `rows` float16 rows
    (RAG_MAX_DOCS by default, the most one search scores). Depends on the size only, not on the
    model, so random unit vectors stand in for real ones."""
    rows = rows or settings.RAG_MAX_DOCS
    rng = np.random.default_rng(0)
    matrix = rng.standard_normal((rows, dims)).astype(np.float32)
    matrix = (matrix / np.linalg.norm(matrix, axis=1, keepdims=True)).astype(np.float16)
    query = rng.standard_normal(dims)
    times = []
    for _ in range(repeats):
        started = time.perf_counter()
        cosine_scores(query, matrix)
        times.append((time.perf_counter() - started) * 1000)
    return float(np.median(times))


def format_models(run: dict) -> str:
    rows = run["models"]
    lines = [
        f"Embedding models on the dev set ({run['meta']['rows']} rows, {run['meta']['questions']} "
        f"questions); cross-validated scores; reference {run['meta']['reference']}",
        f"  {'model':26}{'dims':>5}{'variant':>10}{'thr':>7}{'overall':>9}{'95% CI':>15}"
        f"{'set F1':>8}{'exact':>7}{'r@5':>7}{'no-m':>6}{'vec only':>9}{'docs/s':>8}{'MB':>6}"
        f"  vs reference",
    ]
    for m in rows:
        held, (_, low, high) = m["cross_validated"], m["intervals"]["overall"]
        versus = m["versus_reference"]
        verdict = "reference"
        if versus:
            mean, v_low, v_high = versus["overall"]
            verdict = f"{mean:+.3f} [{v_low:+.3f}, {v_high:+.3f}] {'real' if versus['real'] else 'noise?'}"
        lines.append(
            f"  {m['model']:26}{m['dims']:>5}{m['variant']:>10}{m['threshold']:>7.3f}"
            f"{held['overall']:>9.3f}{f'{low:.3f}-{high:.3f}':>15}{held['set_f1']:>8.3f}"
            f"{held['exact_total']:>7.3f}{held['recall_at_5']:>7.3f}{held['no_match']:>6.2f}"
            f"{m['vector_only']['overall']:>9.3f}{m['docs_per_second'] or 0:>8.0f}"
            f"{m['model_mb'] or 0:>6}  {verdict}"
        )
    kinds = list(rows[0]["by_type"])
    lines += ["", "  Overall by question type (cross-validated):"]
    lines.append(f"  {'model':26}" + "".join(f"{kind:>12}" for kind in kinds))
    for m in rows:
        lines.append(
            f"  {m['model']:26}" + "".join(f"{m['by_type'][k]['overall']:>12.3f}" for k in kinds)
        )
    return "\n".join(lines)

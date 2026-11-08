"""Retrieval metrics on the evaluation set, computed with the production ranking functions.

Each question runs the same steps as a live search: the date phrase sets the period, rows are
ordered newest first, then keyword_ranking, vector_ranking and rrf_fuse rank them. Only the
storage differs: rows come from the committed fixtures instead of the encrypted index.

Ranking metrics (standard IR definitions):
- recall@5: relevant rows in the top 5 / min(5, relevant rows), capped, so a question with 12
  relevant rows can still score 1.
- recall in prompt: the same at RAG_TOP_K, the rows the answer model reads.
- MRR: mean of 1 / rank of the first relevant row (0 if none is found).
- no-match accuracy: share of the no-answer questions for which search returns nothing.

Set metrics: the Ask summary totals every match, not just the top rows, so a wrong row anywhere in
the result changes the total the user reads. Precision, recall and F1 of the whole match set, and
"exact total" (the matches' total for the relevant rows' type equals the true total, to the paisa)
measure that.

Overall: every question counts once: set F1 for a question with an answer, 1 or 0 for "found
nothing" on one without. Tuning maximises it. Averaging set F1 and no-match 50/50 instead let a
few no-answer questions outweigh many answerable ones, and made the tuned threshold unstable.
"""

from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal
from functools import cached_property

import numpy as np
from django.conf import settings

from ai.rag.periods import detect_period
from ai.rag.profiles import Profile
from ai.rag.retriever import (
    keyword_ranking,
    remove_stopwords,
    rrf_fuse,
    tokenize,
    unit_query,
    vector_ranking,
)
from insights.spec import resolve_period

from . import dataset, stats
from .build_dataset import TODAY

K = 5
MODES = ("bm25", "vector", "hybrid")
# Tuning tries thresholds 0.005 apart over the model's own score range (Evaluation.own_grid), and
# scores each by the mean of its neighbourhood: the pick must hold up if the model's scores shift
# slightly, not just sit on the edge of the no-answer questions.
WINDOW = 0.01
FOLDS = 5


@dataclass(frozen=True)
class Outcome:
    """One question's result. A no-answer question is right when `empty`; its other fields stay 0."""

    question: str
    kind: str
    answerable: bool
    empty: bool
    recall_at_5: float = 0.0
    recall_in_prompt: float = 0.0
    reciprocal_rank: float = 0.0
    precision: float = 0.0
    recall: float = 0.0
    f1: float = 0.0
    exact_total: bool = False


def score_question(
    question: str,
    kind: str,
    found: list[str],
    relevant: frozenset[str],
    amounts: dict[str, tuple[str, Decimal]],
    in_prompt: int,
) -> Outcome:
    """Scores one search. `found` is best first; `amounts` maps a row id to (type, amount)."""
    if not relevant:
        return Outcome(question, kind, answerable=False, empty=not found)
    matched = set(found)
    hits = len(relevant & matched)
    precision = hits / len(matched) if matched else 0.0
    recall = hits / len(relevant)
    f1 = 2 * precision * recall / (precision + recall) if hits else 0.0
    first = next((n for n, row in enumerate(found, 1) if row in relevant), None)

    def totals(rows) -> dict[str, Decimal]:
        sums: dict[str, Decimal] = {}
        for row in rows:
            txn_type, amount = amounts[row]
            sums[txn_type] = sums.get(txn_type, Decimal(0)) + amount
        return sums

    wanted, shown = totals(relevant), totals(matched)
    return Outcome(
        question,
        kind,
        answerable=True,
        empty=not found,
        recall_at_5=len(relevant & set(found[:K])) / min(K, len(relevant)),
        recall_in_prompt=len(relevant & set(found[:in_prompt])) / min(in_prompt, len(relevant)),
        reciprocal_rank=1 / first if first else 0.0,
        precision=precision,
        recall=recall,
        f1=f1,
        exact_total=all(shown.get(t, Decimal(0)) == total for t, total in wanted.items()),
    )


@dataclass(frozen=True)
class Metrics:
    recall_at_5: float
    mrr: float
    no_match: float
    set_precision: float
    set_recall: float
    set_f1: float
    exact_total: float
    recall_in_prompt: float
    overall: float  # every question once; what tuning maximises
    outcomes: tuple[Outcome, ...] = field(default=(), repr=False, compare=False)

    @classmethod
    def of(cls, outcomes: list[Outcome]) -> "Metrics":
        answerable = [o for o in outcomes if o.answerable]
        no_answer = [o for o in outcomes if not o.answerable]

        def mean(name: str) -> float:
            return float(np.mean([getattr(o, name) for o in answerable])) if answerable else 0.0

        return cls(
            recall_at_5=mean("recall_at_5"),
            mrr=mean("reciprocal_rank"),
            no_match=sum(o.empty for o in no_answer) / len(no_answer) if no_answer else 1.0,
            set_precision=mean("precision"),
            set_recall=mean("recall"),
            set_f1=mean("f1"),
            exact_total=mean("exact_total"),
            recall_in_prompt=mean("recall_in_prompt"),
            overall=float(np.mean([overall_score(o) for o in outcomes])) if outcomes else 0.0,
            outcomes=tuple(outcomes),
        )

    @property
    def score(self) -> float:
        """What tuning maximises: getting each question's whole match set right (it decides the
        total the user reads), or finding nothing when there is no answer; every question once."""
        return self.overall

    def as_dict(self) -> dict:
        return {
            name: round(getattr(self, name), 4)
            for name in (
                "recall_at_5",
                "mrr",
                "no_match",
                "set_precision",
                "set_recall",
                "set_f1",
                "exact_total",
                "recall_in_prompt",
                "overall",
            )
        }

    def interval(self, name: str) -> stats.Interval:
        """Bootstrap interval of a per-question metric: over every question for "overall", over
        the answerable ones for the rest."""
        if name == "overall":
            return stats.bootstrap_ci([overall_score(o) for o in self.outcomes])
        source = {"mrr": "reciprocal_rank", "set_precision": "precision", "set_recall": "recall",
                  "set_f1": "f1"}.get(name, name)  # fmt: skip
        return stats.bootstrap_ci([getattr(o, source) for o in self.outcomes if o.answerable])


def overall_score(outcome: Outcome) -> float:
    return outcome.f1 if outcome.answerable else float(outcome.empty)


@dataclass(frozen=True)
class CrossValidation:
    picks: list[float]  # the threshold each fold's training part chose
    metrics: Metrics  # every question scored once, by the threshold tuned without it


@dataclass(frozen=True)
class _Question:
    id: str
    kind: str  # the question's type, used to stratify folds and report per type
    candidates: list[int]  # corpus rows in the period, newest first
    keyword: list[int]  # keyword_ranking over the candidates (independent of model and variant)
    relevant: frozenset[str]
    index: int  # row in the question matrices


class Evaluation:
    def __init__(self, split: str = "dev", vectors: dict | None = None):
        """`vectors` replaces the committed vectors, to score another model on the same set."""
        self.split = split
        self._given_vectors = vectors
        self.rows = dataset.corpus(split)
        self.ids = [row["id"] for row in self.rows]
        self.amounts = {row["id"]: (row["txn_type"], Decimal(row["amount"])) for row in self.rows}
        dates = [date.fromisoformat(row["date"]) for row in self.rows]
        tokens = [
            tokenize(f"{text} {row['category']}")
            for text, row in zip(dataset.document_texts(split), self.rows)
        ]
        newest_first = sorted(
            range(len(self.rows)), key=lambda i: (dates[i], self.ids[i]), reverse=True
        )
        self.limit = settings.RAG_MAX_MATCHES
        self.questions = []
        for index, question in enumerate(dataset.questions(split)):
            detected = detect_period(question["question"], TODAY)
            candidates = newest_first
            if detected:
                start, end = resolve_period(detected.date_filter, detected.date_filter, TODAY)
                candidates = [i for i in newest_first if start <= dates[i] <= end]
            query = remove_stopwords(
                tokenize(detected.remainder if detected else question["question"])
            )
            keyword, _ = keyword_ranking(query, [tokens[i] for i in candidates], self.limit)
            relevant = frozenset(question["relevant"])
            kind = question.get("type") or ("answerable" if relevant else "no-answer")
            self.questions.append(
                _Question(question["id"], kind, candidates, keyword, relevant, index)
            )

    @cached_property
    def _vectors(self) -> dict:
        return self._given_vectors or dataset.vectors(self.split)

    def own_grid(self, variant: str, step: float = 0.005) -> tuple:
        """Thresholds spanning this model's own score range: from the lowest to the highest best
        cosine any question gets. Models score on different scales, so one fixed grid would miss
        some models' useful range. It uses no relevance labels, so cross-validation stays honest."""
        tops = []
        for question in self.questions:
            if question.candidates:
                documents = self._vectors["documents"][variant][question.candidates]
                query = unit_query(self._vectors["questions"][variant][question.index])
                tops.append(float((documents.astype(np.float32) @ query).max()))
        low = np.floor(min(tops) / step) * step
        high = np.ceil(max(tops) / step) * step
        return tuple(round(low + step * n, 3) for n in range(int(round((high - low) / step)) + 1))

    def search(self, question: _Question, variant: str, profile: Profile, mode: str) -> list[str]:
        """The ids a live search would return, best first."""
        rankings = []
        if mode in ("bm25", "hybrid"):
            rankings.append(question.keyword)
        if mode in ("vector", "hybrid"):
            vector, _ = vector_ranking(
                self._vectors["questions"][variant][question.index],
                self._vectors["documents"][variant][question.candidates],
                profile,
                settings.RAG_RELATIVE_MARGIN,
                self.limit,
            )
            rankings.append(vector)
        fused = rrf_fuse(rankings, settings.RAG_RRF_K, self.limit)
        return [self.ids[question.candidates[i]] for i, _ in fused]

    def run(self, variant: str, profile: Profile, mode: str = "hybrid", questions=None) -> Metrics:
        outcomes = [
            score_question(
                question.id,
                question.kind,
                self.search(question, variant, profile, mode),
                question.relevant,
                self.amounts,
                settings.RAG_TOP_K,
            )
            for question in (self.questions if questions is None else questions)
        ]
        return Metrics.of(outcomes)

    def tune(
        self, variant: str, profile: Profile, questions=None, grid: tuple | None = None
    ) -> tuple[float, Metrics]:
        """The threshold whose neighbourhood (±WINDOW) has the best mean score; on a tie, the
        one with the higher set recall. Returns it with its own metrics. `grid` defaults to the
        model's own score range."""
        grid = grid or self.own_grid(variant)
        results = {
            t: self.run(variant, profile_with(profile, t), questions=questions) for t in grid
        }

        def neighbourhood(t: float) -> float:
            return float(np.mean([results[u].score for u in grid if abs(u - t) <= WINDOW + 1e-9]))

        best = max(grid, key=lambda t: (round(neighbourhood(t), 6), results[t].set_recall))
        return best, results[best]

    def cross_validate(
        self, variant: str, profile: Profile, k: int = FOLDS, grid: tuple | None = None
    ) -> CrossValidation:
        """Honest scores for a tuned threshold: each fold is scored by the threshold tuned on the
        other folds, so no question helps choose the setting it is scored with."""
        grid = grid or self.own_grid(variant)
        folds = stats.stratified_folds(
            [q.id for q in self.questions], [q.kind for q in self.questions], k
        )
        picks, outcomes = [], []
        for fold in folds:
            held_out = set(fold)
            training = [q for n, q in enumerate(self.questions) if n not in held_out]
            threshold, _ = self.tune(variant, profile, training, grid)
            picks.append(threshold)
            tested = [self.questions[n] for n in fold]
            outcomes.extend(
                self.run(variant, profile_with(profile, threshold), questions=tested).outcomes
            )
        order = {q.id: n for n, q in enumerate(self.questions)}
        outcomes.sort(key=lambda o: order[o.question])
        return CrossValidation(picks, Metrics.of(outcomes))


def profile_with(profile: Profile, threshold: float) -> Profile:
    return replace(profile, min_similarity=threshold)


def production_variant(profile: Profile) -> str:
    """The vectors a live search uses for this profile: with the model's prefixes if it has any."""
    return "prefixed" if profile.doc_prefix or profile.query_prefix else "plain"

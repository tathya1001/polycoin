"""Retrieval metrics on the evaluation set, computed with the production ranking functions.

Each question runs the same steps as a live search: the date phrase sets the period, rows are
ordered newest first, then keyword_ranking, vector_ranking and rrf_fuse rank them. Only the
storage differs: rows come from the committed fixtures instead of the encrypted index.

Metrics (standard IR definitions):
- recall@5: relevant rows in the top 5 / min(5, relevant rows), capped as in BEIR, so a question
  with 12 relevant rows can still score 1.
- MRR: mean of 1 / rank of the first relevant row (0 if none is found).
- no-match accuracy: share of the no-answer questions for which search returns nothing.
"""

from dataclasses import dataclass
from datetime import date
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
    vector_ranking,
)
from insights.spec import resolve_period

from . import dataset
from .build_dataset import TODAY

K = 5
MODES = ("bm25", "vector", "hybrid")
# Thresholds tried when tuning, and the neighbourhood averaged around each: the pick must hold up
# if the model's scores shift slightly, not just sit on the edge of the no-answer questions.
GRID = tuple(round(0.40 + 0.005 * step, 3) for step in range(41))  # 0.400 .. 0.600
WINDOW = 0.01


@dataclass(frozen=True)
class Metrics:
    recall_at_5: float
    mrr: float
    no_match: float

    @property
    def score(self) -> float:
        """What tuning maximises: finding the right rows and saying "nothing" when there is none,
        weighted equally."""
        return (self.recall_at_5 + self.no_match) / 2


@dataclass(frozen=True)
class _Question:
    candidates: list[int]  # corpus rows in the period, newest first
    keyword: list[int]  # keyword_ranking over the candidates (independent of model and variant)
    relevant: frozenset[str]
    index: int  # row in the question matrices


class Evaluation:
    def __init__(self):
        self.rows = dataset.corpus()
        self.ids = [row["id"] for row in self.rows]
        dates = [date.fromisoformat(row["date"]) for row in self.rows]
        tokens = [
            tokenize(f"{text} {row['category']}")
            for text, row in zip(dataset.document_texts(), self.rows)
        ]
        newest_first = sorted(
            range(len(self.rows)), key=lambda i: (dates[i], self.ids[i]), reverse=True
        )
        self.limit = settings.RAG_MAX_MATCHES
        self.questions = []
        for index, question in enumerate(dataset.questions()):
            detected = detect_period(question["question"], TODAY)
            candidates = newest_first
            if detected:
                start, end = resolve_period(detected.date_filter, detected.date_filter, TODAY)
                candidates = [i for i in newest_first if start <= dates[i] <= end]
            query = remove_stopwords(
                tokenize(detected.remainder if detected else question["question"])
            )
            keyword, _ = keyword_ranking(query, [tokens[i] for i in candidates], self.limit)
            self.questions.append(
                _Question(candidates, keyword, frozenset(question["relevant"]), index)
            )

    @cached_property
    def _vectors(self) -> dict:
        return dataset.vectors()

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

    def run(self, variant: str, profile: Profile, mode: str = "hybrid") -> Metrics:
        recall, reciprocal, empty, no_answer = [], [], 0, 0
        for question in self.questions:
            found = self.search(question, variant, profile, mode)
            if not question.relevant:
                no_answer += 1
                empty += not found
                continue
            hits = len(question.relevant & set(found[:K]))
            recall.append(hits / min(K, len(question.relevant)))
            first = next((n for n, row in enumerate(found, 1) if row in question.relevant), None)
            reciprocal.append(1 / first if first else 0.0)
        return Metrics(float(np.mean(recall)), float(np.mean(reciprocal)), empty / no_answer)

    def tune(self, variant: str, profile: Profile) -> tuple[float, Metrics]:
        """The threshold whose neighbourhood (±WINDOW) has the best mean score; on a tie, the
        one with the higher recall. Returns it with its own metrics."""
        results = {
            t: self.run(variant, Profile(profile.doc_prefix, profile.query_prefix, t)) for t in GRID
        }

        def neighbourhood(t: float) -> float:
            return float(np.mean([results[u].score for u in GRID if abs(u - t) <= WINDOW + 1e-9]))

        best = max(GRID, key=lambda t: (round(neighbourhood(t), 6), results[t].recall_at_5))
        return best, results[best]

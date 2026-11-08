"""Statistics for evaluation results: confidence intervals, paired comparisons and folds.

On a set of about a hundred questions, a few points of difference can be noise. These are the
standard checks, written with numpy and the standard library so the production image gains nothing:
- `bootstrap_ci`: a percentile bootstrap interval of a mean, resampling questions with replacement.
- `paired_bootstrap`: the same for the per-question change between two configurations scored on
  the same questions. Pairing removes the spread between easy and hard questions, so it is much
  tighter than comparing two separate intervals.
- `mcnemar_exact`: an exact McNemar test for a yes/no result per question, such as "the total is
  exactly right". Only the questions where the two configurations disagree carry information.
- `stratified_folds`: k folds that each hold a fair share of every question type, fixed by the
  question ids, so a rerun or a reordered file gives the same folds.
"""

import hashlib
import math
from collections import defaultdict
from dataclasses import dataclass

import numpy as np

RESAMPLES = 2000
LEVEL = 0.95
SEED = 2026  # fixed, so a rerun prints the same interval


@dataclass(frozen=True)
class Interval:
    mean: float
    low: float
    high: float

    def excludes_zero(self) -> bool:
        """For a paired change: true when the whole interval is on one side of zero."""
        return self.low > 0 or self.high < 0

    def as_list(self) -> list[float]:
        return [round(self.mean, 4), round(self.low, 4), round(self.high, 4)]


def bootstrap_ci(values, resamples: int = RESAMPLES, level: float = LEVEL, seed: int = SEED):
    """The mean of `values` with its percentile bootstrap interval at `level`."""
    data = np.asarray(values, dtype=float)
    if data.ndim != 1 or data.size == 0:
        raise ValueError("bootstrap_ci needs a non-empty list of numbers")
    rng = np.random.default_rng(seed)
    means = data[rng.integers(0, data.size, size=(resamples, data.size))].mean(axis=1)
    tail = (1 - level) / 2 * 100
    low, high = np.percentile(means, [tail, 100 - tail])
    return Interval(float(data.mean()), float(low), float(high))


def paired_bootstrap(before, after, resamples: int = RESAMPLES, level: float = LEVEL):
    """The mean per-question change (after - before) with its bootstrap interval. The two lists
    must score the same questions in the same order."""
    first, second = np.asarray(before, dtype=float), np.asarray(after, dtype=float)
    if first.shape != second.shape:
        raise ValueError("paired results must cover the same questions")
    return bootstrap_ci(second - first, resamples, level)


def mcnemar_exact(before: list[bool], after: list[bool]) -> float:
    """Two-sided exact McNemar p-value for paired yes/no results.

    b counts questions right before and wrong after, c the reverse. If the change made no
    difference, each disagreement is a fair coin toss, so p = 2 * P(X <= min(b, c)) for
    X ~ Binomial(b + c, 1/2), capped at 1.
    """
    if len(before) != len(after):
        raise ValueError("paired results must cover the same questions")
    b = sum(1 for old, new in zip(before, after) if old and not new)
    c = sum(1 for old, new in zip(before, after) if new and not old)
    n = b + c
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, i) for i in range(min(b, c) + 1)) / 2**n
    return min(1.0, 2 * tail)


def _shuffle_key(item_id: str) -> str:
    return hashlib.sha256(item_id.encode()).hexdigest()


def stratified_folds(ids: list[str], strata: list[str], k: int = 5) -> list[list[int]]:
    """k lists of positions into `ids`, every position in exactly one.

    Within each stratum the items are ordered by a hash of their id and dealt to the folds in
    turn, continuing across strata, so every fold gets a fair share of each stratum and the
    folds' sizes differ by at most one.
    """
    if len(ids) != len(strata):
        raise ValueError("every id needs a stratum")
    if len(set(ids)) != len(ids):
        raise ValueError("ids must be unique")
    if not 2 <= k <= len(ids):
        raise ValueError("k must be between 2 and the number of items")
    groups: dict[str, list[int]] = defaultdict(list)
    for position, stratum in enumerate(strata):
        groups[stratum].append(position)
    folds: list[list[int]] = [[] for _ in range(k)]
    turn = 0
    for stratum in sorted(groups):
        for position in sorted(groups[stratum], key=lambda p: _shuffle_key(ids[p])):
            folds[turn % k].append(position)
            turn += 1
    return [sorted(fold) for fold in folds]

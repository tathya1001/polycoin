import re
from collections.abc import Hashable
from typing import NamedTuple

import numpy as np
from numpy.typing import ArrayLike, NDArray

from transactions.importer import _IFSC, _NOISE_WORDS, _REFERENCE_LIKE

Vector = NDArray[np.float64]

# Some banks start narrations with "TO TRANSFER-" / "BY TRANSFER-". It is a bank prefix, not the
# user's words, and left in it makes every such row look like the "Transfer" category.
_TRANSFER_PREFIX = re.compile(r"(?i)^\s*(?:to|by)\s+transfer\s*-?\s*")


def prepare_text(name: str, description: str, notes: str = "") -> str:
    """The string we embed: name, the user's own notes, and a noise-stripped narration.

    'UPI/DR/412345678901/TASTYBITES/TSTB0000001/tastybites@tstb' is mostly reference numbers and
    bank codes. Left in, they drag every transaction's vector toward every other. A UPI
    handle keeps the part before the '@' (often the only place the merchant appears).
    Notes come before the narration so the length cap trims bank noise, not the user's words.
    """
    description = _TRANSFER_PREFIX.sub("", description)
    text = _IFSC.sub(" ", f"{name} {notes} {description}")
    tokens, seen = [], set()
    for token in re.split(r"[/*\s\-]+", text):
        token = token.split("@", 1)[0]  # 'tastybites@tstb' -> 'tastybites'; the bank after @ is noise
        lowered = token.lower()
        if not token or lowered in seen or lowered in _NOISE_WORDS:
            continue
        if token.isdigit():
            continue
        if len(token) >= 6 and _REFERENCE_LIKE.fullmatch(token):
            continue
        seen.add(lowered)
        tokens.append(token)
    return " ".join(tokens)[:300] or name


def normalize(vectors: ArrayLike) -> Vector:
    """Scale to unit length along the last axis, so only direction counts.

    Accepts one vector (n,) or a stack of them (m, n). Zero vectors stay zero.
    """
    array = np.asarray(vectors, dtype=np.float64)
    lengths = np.linalg.norm(array, axis=-1, keepdims=True)
    return array / np.where(lengths == 0, 1.0, lengths)


def cosine_similarities(vector: ArrayLike, matrix: ArrayLike) -> Vector:
    """Cosine similarity of one vector against every row of `matrix`.

    Vectors from different models live in unrelated spaces, so a size mismatch raises
    instead of returning a meaningless number.
    """
    vector = np.asarray(vector, dtype=np.float64)
    matrix = np.atleast_2d(np.asarray(matrix, dtype=np.float64))
    if matrix.shape[1] != vector.shape[0]:
        raise ValueError("Vectors have different dimensions.")
    return normalize(matrix) @ normalize(vector)


def build_prototype(
    label_vec: ArrayLike,
    example_vecs: ArrayLike,
    full_at: int,
    max_weight: float,
) -> Vector:
    """One vector representing a category.

    No examples -> the label alone. With examples, the label is pulled toward the centroid
    of the user's own transactions in that category. The pull grows with the number of
    examples and stops at `max_weight` once there are `full_at` of them, so the label
    always keeps some say.
    """
    label = normalize(label_vec)
    if len(example_vecs) == 0:
        return label

    weight = min(len(example_vecs), full_at) / full_at * max_weight
    center = normalize(normalize(example_vecs).mean(axis=0))
    return normalize((1 - weight) * label + weight * center)


class Decision(NamedTuple):
    category_id: Hashable | None  # whatever key the caller used, e.g. a Category UUID
    score: float | None
    runner_up_id: Hashable | None
    runner_up_score: float | None
    decision: str  # "propose" | "below_threshold" | "too_close" | "no_candidates"


def decide(
    txn_vec: ArrayLike,
    prototypes: dict[Hashable, Vector],
    min_score: float,
    min_margin: float,
) -> Decision:
    """Pick the nearest prototype, but only call it a proposal if it's clearly right.

    Two independent guards: the best score must clear `min_score`, and it must beat the
    runner-up by `min_margin`. Without the margin, 0.61 Food vs 0.60 Groceries would be a
    coin-flip presented as a confident answer.
    """
    if not prototypes:
        return Decision(None, None, None, None, "no_candidates")

    ids = list(prototypes)
    scores = cosine_similarities(txn_vec, np.vstack(list(prototypes.values())))

    # Highest score first. The sort is stable, so ties keep the mapping's own order and
    # results stay deterministic.
    order = np.argsort(-scores, kind="stable")
    best, runner = order[0], (order[1] if len(order) > 1 else None)

    best_score = float(scores[best])
    runner_score = float(scores[runner]) if runner is not None else None

    if best_score < min_score:
        verdict = "below_threshold"
    elif runner_score is not None and best_score - runner_score < min_margin:
        verdict = "too_close"
    else:
        verdict = "propose"

    return Decision(
        ids[best],
        best_score,
        ids[runner] if runner is not None else None,
        runner_score,
        verdict,
    )


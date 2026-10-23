"""Loads the retrieval evaluation set and its committed vectors.

rag_corpus.json and rag_questions.json come from build_dataset.py; rag_vectors.json comes from
the embed_rag_eval command, which embeds those texts once with a local Ollama. The vectors are
committed, so CI evaluates retrieval with no model at all.
"""

import base64
import hashlib
import json
from functools import cache
from pathlib import Path

import numpy as np

from ai.rag.profiles import TEXT_VERSION
from ai.scoring import prepare_text

HERE = Path(__file__).parent
VECTORS = HERE / "rag_vectors.json"
VARIANTS = ("plain", "prefixed")  # without and with the model's task prefixes


def _load(filename: str):
    return json.loads((HERE / filename).read_text(encoding="utf-8"))


@cache
def corpus() -> list[dict]:
    return _load("rag_corpus.json")


@cache
def questions() -> list[dict]:
    return _load("rag_questions.json")


def document_texts() -> list[str]:
    """What gets embedded and keyword-searched for each row, as the live index builds it."""
    return [prepare_text(row["name"], row["description"], row["notes"]) for row in corpus()]


def question_texts() -> list[str]:
    return [question["question"] for question in questions()]


def fingerprint() -> str:
    """Changes whenever an embedded text changes, so stale vectors can't pass unnoticed."""
    payload = {
        "text_version": TEXT_VERSION,
        "documents": document_texts(),
        "questions": question_texts(),
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode()).hexdigest()


def encode(vectors: np.ndarray) -> list[str]:
    """Rows of a float16 matrix as base64 strings, little-endian."""
    return [base64.b64encode(row.astype("<f2").tobytes()).decode() for row in vectors]


def decode(rows: list[str], dims: int) -> np.ndarray:
    data = b"".join(base64.b64decode(row) for row in rows)
    return np.frombuffer(data, dtype="<f2").reshape(len(rows), dims)


@cache
def vectors() -> dict:
    """{"model", "digest", "dims", "fingerprint", "documents": {variant: matrix},
    "questions": {variant: matrix}}, with float16 matrices in corpus and question order."""
    raw = json.loads(VECTORS.read_text(encoding="utf-8"))
    dims = raw["dims"]
    return {
        **{key: raw[key] for key in ("model", "digest", "dims", "fingerprint")},
        "documents": {v: decode(raw["documents"][v], dims) for v in VARIANTS},
        "questions": {v: decode(raw["questions"][v], dims) for v in VARIANTS},
    }

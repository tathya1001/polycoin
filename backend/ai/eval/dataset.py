"""Loads the retrieval evaluation sets and their committed vectors.

Two splits: "dev" (tuning, cross-validation, CI gates) and "test" (locked; scored only for the
final held-out numbers). The corpus and question files come from build_dataset.py; the vectors
come from the embed_rag_eval command, which embeds those texts once with a local Ollama. The
vectors are committed, so CI evaluates retrieval with no model at all.
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
SPLITS = ("dev", "test")
VARIANTS = ("plain", "prefixed")  # without and with the model's task prefixes


def _prefix(split: str) -> str:
    if split not in SPLITS:
        raise ValueError(f"split is one of {SPLITS}")
    return "rag" if split == "dev" else "rag_test"


def _load(filename: str):
    return json.loads((HERE / filename).read_text(encoding="utf-8"))


@cache
def corpus(split: str = "dev") -> list[dict]:
    return _load(f"{_prefix(split)}_corpus.json")


@cache
def questions(split: str = "dev") -> list[dict]:
    return _load(f"{_prefix(split)}_questions.json")


def document_texts(split: str = "dev") -> list[str]:
    """What gets embedded and keyword-searched for each row, as the live index builds it."""
    return [prepare_text(row["name"], row["description"], row["notes"]) for row in corpus(split)]


def question_texts(split: str = "dev") -> list[str]:
    return [question["question"] for question in questions(split)]


def fingerprint(split: str = "dev") -> str:
    """Changes whenever an embedded text changes, so stale vectors can't pass unnoticed."""
    payload = {
        "text_version": TEXT_VERSION,
        "documents": document_texts(split),
        "questions": question_texts(split),
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode()).hexdigest()


def content_digest(split: str) -> str:
    """Changes whenever anything in the split changes, including types and relevant rows. The
    locked test set's digest is pinned, so its answers can't be edited after seeing results."""
    payload = {"corpus": corpus(split), "questions": questions(split)}
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()


def vectors_path(split: str = "dev") -> Path:
    return HERE / f"{_prefix(split)}_vectors.json"


def encode(vectors: np.ndarray) -> list[str]:
    """Rows of a float16 matrix as base64 strings, little-endian."""
    return [base64.b64encode(row.astype("<f2").tobytes()).decode() for row in vectors]


def decode(rows: list[str], dims: int) -> np.ndarray:
    data = b"".join(base64.b64decode(row) for row in rows)
    return np.frombuffer(data, dtype="<f2").reshape(len(rows), dims)


@cache
def vectors(split: str = "dev") -> dict:
    """The committed vectors of one split; see load_vectors."""
    return load_vectors(vectors_path(split))


def load_vectors(path: Path) -> dict:
    """{"model", "digest", "dims", "fingerprint", "documents": {variant: matrix},
    "questions": {variant: matrix}, "timing": {...} or None}, with float16 matrices in corpus
    and question order."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    dims = raw["dims"]
    return {
        **{key: raw[key] for key in ("model", "digest", "dims", "fingerprint")},
        "timing": raw.get("timing"),
        "documents": {v: decode(raw["documents"][v], dims) for v in VARIANTS},
        "questions": {v: decode(raw["questions"][v], dims) for v in VARIANTS},
    }

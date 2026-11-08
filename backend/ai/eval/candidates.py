"""Embedding models the benchmark compares, and where their evaluation vectors are cached.

Production settings live in ai.rag.profiles; this list is only for comparing models. Each entry is
the task prefixes the model's own card documents for search (document, query); an empty pair
means the model is used as is. A model with a production profile uses that profile's prefixes.

Only the production model's vectors are committed (CI needs them). The others are cached in
ai/eval/.cache/, which git ignores: they are about 2 MB per model and can be rebuilt any time.
"""

import json
import re
from pathlib import Path

from ai.rag.profiles import PROFILES, base_name, profile_for

CACHE = Path(__file__).parent / ".cache"

PREFIXES = {
    "all-minilm": ("", ""),
    "bge-m3": ("", ""),
    "embeddinggemma": ("title: none | text: ", "task: search result | query: "),
    # Documents as they are; queries with the card's default instruction for search.
    "qwen3-embedding": (
        "",
        "Instruct: Given a web search query, retrieve relevant passages that answer the query\n"
        "Query:",
    ),
}


def prefixes_for(model: str) -> tuple[str, str]:
    """(document prefix, query prefix) for a model: its production profile's, else the list's."""
    name = base_name(model)
    if name in PROFILES:
        profile = profile_for(model)
        return profile.doc_prefix, profile.query_prefix
    if name not in PREFIXES:
        raise ValueError(f"{model} is not a benchmark candidate. Add its prefixes to PREFIXES.")
    return PREFIXES[name]


def cache_path(model: str, split: str) -> Path:
    slug = re.sub(r"[^a-z0-9]+", "-", base_name(model)).strip("-")
    return CACHE / f"{slug}-{split}.json"


def cached_models() -> list[str]:
    """Model tags with cached dev vectors, in name order."""
    if not CACHE.exists():
        return []
    return sorted(
        json.loads(path.read_text(encoding="utf-8"))["model"] for path in CACHE.glob("*-dev.json")
    )

"""Embeds the evaluation set with a local Ollama and writes rag_vectors.json. Dev machine only.

Uses only the standard library, so it adds no dependency to the production image. The server
never calls Ollama in production; this runs once by hand (`python manage.py embed_rag_eval`), and
its output is committed.
"""

import json
import socket
import urllib.parse
import urllib.request
from datetime import date

import numpy as np

from ai.rag.profiles import profile_for

from . import dataset

DEFAULT_URL = "http://host.docker.internal:11434"  # the host's Ollama, from inside Docker
BATCH = 32
TIMEOUT = 120  # seconds per request; the first one also loads the model


def ipv4_url(url: str) -> str:
    """The URL with its host resolved to IPv4.

    Docker Desktop resolves host.docker.internal to an IPv6 address first, which containers
    often can't route; urllib then fails instead of trying the IPv4 address.
    """
    parts = urllib.parse.urlsplit(url)
    address = socket.getaddrinfo(parts.hostname, parts.port, socket.AF_INET)[0][4][0]
    netloc = f"{address}:{parts.port}" if parts.port else address
    return urllib.parse.urlunsplit(parts._replace(netloc=netloc))


def _call(base: str, path: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        f"{base}{path}", data=data, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return json.load(response)


def model_digest(base: str, model: str) -> str:
    for tag in _call(base, "/api/tags")["models"]:
        if tag["name"] == model:
            return tag["digest"]
    raise SystemExit(f"{model} is not installed in this Ollama. Run: ollama pull {model}")


def embed(base: str, model: str, texts: list[str]) -> np.ndarray:
    """Unit-length float16 vectors, one per text, in order."""
    rows = []
    for start in range(0, len(texts), BATCH):
        body = {"model": model, "input": texts[start : start + BATCH]}
        rows.extend(_call(base, "/api/embed", body)["embeddings"])
    matrix = np.asarray(rows, dtype=np.float64)
    matrix /= np.linalg.norm(matrix, axis=1, keepdims=True)
    return matrix.astype(np.float16)


def write_vectors(url: str, model: str) -> str:
    """Embeds documents and questions, with and without the model's prefixes. Returns a summary."""
    base = ipv4_url(url)
    digest = model_digest(base, model)
    profile = profile_for(model)
    documents, questions = dataset.document_texts(), dataset.question_texts()
    variants = {
        "plain": ("", ""),
        "prefixed": (profile.doc_prefix, profile.query_prefix),
    }
    output = {
        "model": model,
        "digest": digest,
        "fingerprint": dataset.fingerprint(),
        "created": date.today().isoformat(),
        "documents": {},
        "questions": {},
    }
    for variant, (doc_prefix, query_prefix) in variants.items():
        doc_matrix = embed(base, model, [doc_prefix + text for text in documents])
        query_matrix = embed(base, model, [query_prefix + text for text in questions])
        output["dims"] = int(doc_matrix.shape[1])
        output["documents"][variant] = dataset.encode(doc_matrix)
        output["questions"][variant] = dataset.encode(query_matrix)
    dataset.VECTORS.write_text(json.dumps(output, indent=1) + "\n", encoding="utf-8")
    return (
        f"{len(documents)} documents and {len(questions)} questions embedded with {model} "
        f"({digest[:12]}), {output['dims']} dimensions"
    )

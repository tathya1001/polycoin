"""Embeds the evaluation sets with a local Ollama and writes their vector files. Dev machine only.

Uses only the standard library, so it adds no dependency to the production image. The server
never calls Ollama in production; this runs by hand (`python manage.py embed_rag_eval`). The
production model's output is committed; other models' goes to the benchmark's cache.
"""

import json
import socket
import time
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

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


def model_info(base: str, model: str) -> dict:
    """{"digest", "size", "duplicates"}: the installed model's digest, its size on disk in bytes,
    and how many entries the model list has under this name. Ollama can list one tag twice with
    different digests; the vectors are the same, so the first digest in sorted order is recorded,
    which keeps the record the same from run to run."""
    entries = sorted(
        (tag for tag in _call(base, "/api/tags")["models"] if tag["name"] == model),
        key=lambda tag: tag["digest"],
    )
    if not entries:
        raise SystemExit(f"{model} is not installed in this Ollama. Run: ollama pull {model}")
    return {"digest": entries[0]["digest"], "size": entries[0]["size"], "duplicates": len(entries)}


def embed(base: str, model: str, texts: list[str]) -> np.ndarray:
    """Unit-length float16 vectors, one per text, in order."""
    rows = []
    for start in range(0, len(texts), BATCH):
        body = {"model": model, "input": texts[start : start + BATCH]}
        rows.extend(_call(base, "/api/embed", body)["embeddings"])
    matrix = np.asarray(rows, dtype=np.float64)
    matrix /= np.linalg.norm(matrix, axis=1, keepdims=True)
    return matrix.astype(np.float16)


def write_vectors(
    url: str,
    model: str,
    split: str = "dev",
    prefixes: tuple[str, str] | None = None,
    path: Path | None = None,
) -> str:
    """Embeds one split's documents and questions, with and without the model's prefixes, and
    times the documents. `prefixes` (document, query) default to the model's production profile;
    `path` to the committed vector file. Returns a summary."""
    base = ipv4_url(url)
    info = model_info(base, model)
    if prefixes is None:
        profile = profile_for(model)
        prefixes = (profile.doc_prefix, profile.query_prefix)
    documents, questions = dataset.document_texts(split), dataset.question_texts(split)
    embed(base, model, ["warm-up"])  # loads the model, so loading isn't timed
    output = {
        "model": model,
        "digest": info["digest"],
        "fingerprint": dataset.fingerprint(split),
        "created": date.today().isoformat(),
        "timing": {"model_bytes": info["size"], "documents": len(documents)},
        "documents": {},
        "questions": {},
    }
    for variant, (doc_prefix, query_prefix) in (("plain", ("", "")), ("prefixed", prefixes)):
        if variant == "prefixed" and not any(prefixes):  # the same texts: reuse, don't re-embed
            output["documents"]["prefixed"] = output["documents"]["plain"]
            output["questions"]["prefixed"] = output["questions"]["plain"]
            continue
        started = time.perf_counter()
        doc_matrix = embed(base, model, [doc_prefix + text for text in documents])
        output["timing"][f"{variant}_seconds"] = round(time.perf_counter() - started, 3)
        query_matrix = embed(base, model, [query_prefix + text for text in questions])
        output["dims"] = int(doc_matrix.shape[1])
        output["documents"][variant] = dataset.encode(doc_matrix)
        output["questions"][variant] = dataset.encode(query_matrix)
    target = path or dataset.vectors_path(split)
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(output, indent=1) + "\n", encoding="utf-8")
    seconds = output["timing"]["plain_seconds"]
    note = f" (Ollama lists this tag {info['duplicates']} times)" if info["duplicates"] > 1 else ""
    return (
        f"{split}: {len(documents)} documents and {len(questions)} questions embedded with "
        f"{model} ({info['digest'][:12]}){note}, {output['dims']} dimensions, "
        f"{len(documents) / seconds:.0f} documents a second"
    )

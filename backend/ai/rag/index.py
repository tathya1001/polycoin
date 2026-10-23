"""Indexing for "Ask your transactions": which rows need a vector, and storing what comes back.

Only the browser can reach the user's own Ollama, so the work is split: `pending` hands out
document texts, the browser embeds them, and `store_vectors` encrypts and stores the vectors.
Decrypted text lives only in memory here: never log or persist it.
"""

import logging
import uuid

import numpy as np
from django.conf import settings
from django.db.models import F, Q

from ai.models import RagDocument
from ai.scoring import prepare_text
from ai.services import decrypt_fields
from transactions.models import Transaction
from vault.services import UserCipher

from . import codec
from .errors import RagError
from .profiles import TEXT_VERSION, profile_for

logger = logging.getLogger(__name__)

DOC_CONTEXT = "rag.doc"  # vault context of payload_enc
TEXT_CONTEXT = "rag.text"  # blind-index context of text_hash
SCAN_CHUNK = 500  # rows decrypted per query while `pending` looks for work


def document_text(cipher: UserCipher, txn: Transaction) -> str:
    """What is embedded and keyword-searched: the cleaned text categorisation uses too."""
    return prepare_text(*decrypt_fields(cipher, txn))


def version_of(txn: Transaction) -> str:
    """The row's version for race-safe storing: its last change, as exact text."""
    return txn.updated_at.isoformat()


def _text_hash(cipher: UserCipher, text: str) -> bytes:
    return cipher.blind_index(text.encode(), TEXT_CONTEXT)


def _fresh(model: str, digest: str) -> Q:
    """A transaction whose document is current: same model, digest and text version, and
    embedded at or after the row's last change."""
    return Q(
        rag_document__model=model,
        rag_document__model_digest=digest,
        rag_document__text_version=TEXT_VERSION,
        rag_document__source_updated_at__gte=F("updated_at"),
    )


def _same_index(doc: RagDocument, model: str, digest: str) -> bool:
    return (doc.model, doc.model_digest, doc.text_version) == (model, digest, TEXT_VERSION)


def pending(user, model: str, digest: str, limit: int) -> dict:
    """Up to `limit` rows that need embedding, newest first: {items, remaining}.

    A row needs work when it has no document, its document is for another model, digest or
    TEXT_VERSION, or the row changed after it was embedded. In the last case the text often did
    not change: a new category, say, which search matches by name and keeps out of the vector. So
    the text hash is compared first, and a match only moves `source_updated_at` forward, with no
    re-embed.

    Each item is {transaction, version, text}; the text carries the model's document prefix,
    and `version` must come back with the vector. `remaining` counts the rows still needing work
    once these items are stored.
    """
    prefix = profile_for(model).doc_prefix
    candidates = (
        Transaction.objects.filter(user=user)
        .exclude(_fresh(model, digest))
        .select_related("rag_document")
        .defer("amount_enc", "balance_enc", "fingerprint", "rag_document__payload_enc")
        .order_by("-date", "-created_at", "id")
    )
    count = candidates.count()
    cipher = UserCipher(user)
    items, bumped = [], []
    # Slices, not .iterator(): server-side cursors break behind a transaction-mode pooler.
    for start in range(0, count, SCAN_CHUNK):
        for txn in candidates[start : start + SCAN_CHUNK]:
            if len(items) >= limit:
                break
            text = document_text(cipher, txn)
            doc = getattr(txn, "rag_document", None)  # a missing one raises an AttributeError
            if (
                doc is not None
                and _same_index(doc, model, digest)
                and bytes(doc.text_hash) == _text_hash(cipher, text)
            ):
                doc.source_updated_at = txn.updated_at
                bumped.append(doc)
                continue
            items.append(
                {"transaction": str(txn.id), "version": version_of(txn), "text": prefix + text}
            )
        if len(items) >= limit:
            break

    RagDocument.objects.bulk_update(bumped, ["source_updated_at"])
    return {"items": items, "remaining": count - len(bumped) - len(items)}


def _unit(vector) -> np.ndarray | None:
    """The vector scaled to length 1, so cosine similarity is a dot product; None if unusable."""
    try:
        values = np.asarray(vector, dtype=np.float64)
    except (TypeError, ValueError):
        return None
    if values.ndim != 1 or values.size == 0 or not np.isfinite(values).all():
        return None
    norm = np.linalg.norm(values)
    return values / norm if norm > 0 else None


def _uuid(value) -> uuid.UUID | None:
    try:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except ValueError:
        return None


def store_vectors(user, model: str, digest: str, items: list[dict]) -> dict:
    """Encrypts and stores one batch of the browser's vectors: {stored, stale, rejected}.

    `items` are [{transaction, version, vector}] for rows `pending` handed out.
    - rejected: not this user's transaction, a repeat within the batch, or a vector that is not
      a usable embedding. Another user's id stores nothing and reveals nothing.
    - stale: the row changed after `pending` handed it out; it comes back in the next batch.

    Every vector in a batch must have one size, the size of the user's documents already stored
    for this model and digest; otherwise RagError("dimension_mismatch"). The text is rebuilt
    here from the row, never taken from the browser.
    """
    sizes = {len(item["vector"]) for item in items}
    if len(sizes) > 1:
        raise RagError("dimension_mismatch", "Every vector in a batch must have the same size.")
    existing = (
        RagDocument.objects.filter(user=user, model=model, model_digest=digest)
        .values_list("dims", flat=True)
        .first()
    )
    if existing is not None and sizes and existing not in sizes:
        raise RagError(
            "dimension_mismatch",
            f"This model's stored vectors have {existing} dimensions, not {sizes.pop()}.",
        )

    ids = [_uuid(item["transaction"]) for item in items]
    txns = Transaction.objects.filter(user=user).in_bulk([i for i in ids if i is not None])
    cipher = UserCipher(user)
    docs, seen, stale, rejected = [], set(), 0, 0
    for txn_id, item in zip(ids, items):
        txn = txns.get(txn_id)
        if txn is None or txn_id in seen:
            rejected += 1
            continue
        seen.add(txn_id)
        if version_of(txn) != item["version"]:
            stale += 1
            continue
        vector = _unit(item["vector"])
        text = document_text(cipher, txn)
        try:
            payload = codec.pack(vector, text) if vector is not None else None
        except ValueError:  # more dimensions than RAG_MAX_DIMS
            payload = None
        if payload is None:
            rejected += 1
            continue
        docs.append(
            RagDocument(
                user=user,
                transaction=txn,
                model=model,
                model_digest=digest,
                dims=vector.size,
                text_version=TEXT_VERSION,
                payload_enc=cipher.encrypt(payload, DOC_CONTEXT),
                text_hash=_text_hash(cipher, text),
                source_updated_at=txn.updated_at,
            )
        )

    # One statement, so two tabs indexing at once can't collide on the one-per-transaction rule.
    RagDocument.objects.bulk_create(
        docs,
        update_conflicts=True,
        unique_fields=["transaction"],
        update_fields=[
            "model", "model_digest", "dims", "text_version", "payload_enc", "text_hash",
            "source_updated_at", "updated_at",
        ],
    )  # fmt: skip
    logger.info("rag index batch: stored=%d stale=%d rejected=%d", len(docs), stale, rejected)
    return {"stored": len(docs), "stale": stale, "rejected": rejected}


def status(user, model: str, digest: str) -> dict:
    """{enabled, indexed, total, profile}: how much of the user's history is searchable with
    this model, and the prefixes the browser needs to embed for it."""
    mine = Transaction.objects.filter(user=user)
    return {
        "enabled": settings.RAG_ENABLED,
        "indexed": mine.filter(_fresh(model, digest)).count(),
        "total": mine.count(),
        "profile": profile_for(model).as_dict(),
    }


def clear(user) -> int:
    """Deletes the user's whole index ("Clear index"). Returns how many documents went."""
    deleted, _ = RagDocument.objects.filter(user=user).delete()
    return deleted

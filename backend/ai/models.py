from django.db import models
from django.db.models import Q

from core.models import OwnedModel

MAX_DIMS = 4096  # the largest embedding we store; settings.RAG_MAX_DIMS may only lower it


class RagDocument(OwnedModel):
    """One transaction's search document for "Ask your transactions".

    The vector and the cleaned text are encrypted together in `payload_enc` (ai/rag/codec.py):
    embeddings can be turned back into text, so they get the same protection as the text.
    The plain columns say nothing about the user's money: which model made the vector, its size,
    and the versions that decide when the document is stale (ai/rag/index.py).
    """

    transaction = models.OneToOneField(
        "transactions.Transaction", on_delete=models.CASCADE, related_name="rag_document"
    )
    model = models.CharField(max_length=100)  # the Ollama name, e.g. "nomic-embed-text:latest"
    model_digest = models.CharField(max_length=80)  # a tag can move after `ollama pull`
    dims = models.PositiveSmallIntegerField()
    text_version = models.PositiveSmallIntegerField()  # profiles.TEXT_VERSION when embedded
    payload_enc = models.BinaryField()  # vault ciphertext, context "rag.doc"
    text_hash = models.BinaryField(max_length=32)  # blind_index(text, "rag.text")
    source_updated_at = models.DateTimeField()  # transaction.updated_at when embedded

    class Meta:
        indexes = [models.Index(fields=["user", "model", "model_digest"])]
        constraints = [
            models.CheckConstraint(
                condition=Q(dims__gte=1, dims__lte=MAX_DIMS), name="ragdocument_dims_in_range"
            ),
        ]

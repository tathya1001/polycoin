"""Per-model retrieval settings, and the versions that tie stored data to the code.

Embedding models score on different scales, so one global similarity threshold would be wrong for
other models. Even for one model the bands overlap: on the evaluation set, nomic-embed-text gives
questions with no answer up to 0.51 against their closest row, while some real matches score 0.46,
which is why keywords and vectors are combined. A model without a profile still works: search
falls back to a relative rule, and the page shows an "untuned model" note.
"""

from dataclasses import dataclass

# Raise when the document text changes (ai.scoring.prepare_text, or what goes into it): every
# document embedded under an older version then counts as stale and is re-embedded.
TEXT_VERSION = 1
# Sent with every ask and logged, so each evaluation result is tied to the exact prompt.
PROMPT_VERSION = "rag-v2"


@dataclass(frozen=True)
class Profile:
    doc_prefix: str  # put before each document's text when it is embedded
    query_prefix: str  # put before the question when it is embedded
    # The lowest cosine similarity that counts as a match, tuned on the evaluation set.
    # None: not tuned yet, so search keeps rows within RAG_RELATIVE_MARGIN of the best score.
    min_similarity: float | None = None

    @property
    def tuned(self) -> bool:
        return self.min_similarity is not None

    def as_dict(self) -> dict:
        """What the browser needs: the prefixes to embed with, and whether to show "untuned"."""
        return {
            "doc_prefix": self.doc_prefix,
            "query_prefix": self.query_prefix,
            "tuned": self.tuned,
        }


UNTUNED = Profile(doc_prefix="", query_prefix="")

PROFILES = {
    # Task prefixes from nomic's model card; on the evaluation set they beat plain text. The
    # threshold is what ai/eval/evaluate.py's tuning picks (tuned 2026-10-23, digest
    # 0a109f422b47): hybrid recall@5 0.872, MRR 0.875, and every no-answer question finds nothing.
    # ai/test_rag_eval.py fails if a change to the data or the ranking moves the pick.
    "nomic-embed-text": Profile(
        doc_prefix="search_document: ", query_prefix="search_query: ", min_similarity=0.52
    ),
}


def base_name(model_name: str) -> str:
    """'nomic-embed-text:latest' -> 'nomic-embed-text', in lower case.

    Only a trailing tag goes: in 'host:5000/name' the colon belongs to the registry address. A
    namespaced name ('someone/nomic-embed-text') stays as it is, since it may be another model.
    """
    name = model_name.strip().lower()
    head, colon, tag = name.rpartition(":")
    return head if colon and head and "/" not in tag else name


def profile_for(model_name: str) -> Profile:
    return PROFILES.get(base_name(model_name), UNTUNED)

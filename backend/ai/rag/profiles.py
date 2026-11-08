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
    # Raise when doc_prefix changes (including when a profile first gives a model a prefix): the
    # model's documents embedded under an older revision then count as stale. See text_version_for.
    revision: int = 0

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
    # threshold comes from ai/eval/evaluate.py's tuning (tuned 2026-10-23, digest 0a109f422b47).
    # Re-checked 2026-11-06 on the 149-question dev set, where tuning picks 0.525: 0.52 is inside
    # the ±0.01 window tuning treats as equal, so it stays. There, hybrid recall@5 is 0.726, set
    # F1 0.625. ai/test_rag_eval.py fails if a change to the data or the ranking moves the pick
    # further than that window.
    "nomic-embed-text": Profile(
        doc_prefix="search_document: ", query_prefix="search_query: ", min_similarity=0.52
    ),
    # The suggested model since 2026-11-06. On the 149-question dev set, cross-validated, with
    # thresholds tuned over its own score range: overall 0.616 against nomic's 0.573, typo
    # questions +0.21 (a real gain), dated questions -0.08. Prefixes from its model card: plain text
    # scores 0.571. Revision 1: before this profile it was untuned and embedded with no prefix.
    "embeddinggemma": Profile(
        doc_prefix="title: none | text: ",
        query_prefix="task: search result | query: ",
        min_similarity=0.355,
        revision=1,
    ),
    # Plain text (its card documents no prefixes). Same evaluation: overall 0.551, and the threshold
    # is stable across folds (0.52-0.53).
    "bge-m3": Profile(doc_prefix="", query_prefix="", min_similarity=0.525),
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


def text_version_for(model_name: str) -> int:
    """The text version this model's documents are stored with and must have to count as
    current: TEXT_VERSION, plus 1000 for each revision of the model's profile. A document embedded
    before its model's prefix changed then no longer matches and is embedded again, while revision
    0 keeps plain TEXT_VERSION, so other models' documents stay current."""
    return TEXT_VERSION + 1000 * profile_for(model_name).revision

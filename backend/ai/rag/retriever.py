"""Hybrid search over one user's encrypted documents: BM25 + exact cosine, fused with RRF.

The database cannot read the vectors or the text, so search runs here, after decryption:
1. SQL picks the user's documents for this model in the period, newest first, at most
   RAG_MAX_DOCS. Period and type are plaintext columns, so they filter first.
2. One pass decrypts and unpacks them.
3. Keywords (BM25 over the text plus the live category name) and vectors (exact cosine) each
   rank their matches. RRF fuses the two rankings by rank, so their scores never need calibrating.

`EncryptedHybridRetriever` implements LangChain's `BaseRetriever`, the interface vector stores
implement too, so an agent can use it as a tool unchanged. Its `search()` also
returns what the ask response needs besides the documents: coverage, period and timings.
Decrypted text lives only in memory here: never log or persist it.
"""

import gc
import re
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import numpy as np
import psycopg
from django.conf import settings
from django.db import connection
from django.db.models import Count, Min
from django.utils import timezone
from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from rank_bm25 import BM25Okapi

from ai.models import RagDocument
from categories.models import Category
from insights.spec import (
    MAX_DATA_SOURCES,
    MIN_DATE,
    TXN_TYPES,
    SpecError,
    resolve_period,
    validate_date_filter,
)
from transactions.models import Transaction
from vault.services import UserCipher

from . import codec
from .errors import RagError
from .index import DOC_CONTEXT
from .periods import detect_period
from .profiles import TEXT_VERSION, Profile, profile_for

COSINE_CHUNK = 2048  # rows widened to float32 at a time, so 8k rows never need 25 MB at once

_TOKEN = re.compile(r"[^\W_]+")  # runs of letters and digits, in any script


def stem(word: str) -> str:
    """English plurals to their singular: "groceries" -> "grocery", "tickets" -> "ticket".

    Harman's S-stemmer (1991), as Lucene's EnglishMinimalStemmer implements it. Applied to the
    documents and the question alike, so a plural in one matches a singular in the other; on
    the evaluation set it lifted keyword recall@5 from 0.58 to 0.69 with no false matches.
    """
    if len(word) < 3 or word[-1] != "s" or word[-2] in "us":
        return word
    if word[-2] == "e":
        if len(word) > 3 and word[-3] == "i" and word[-4] not in "ae":
            return word[:-3] + "y"
        if word[-3] in "iaoe":
            return word
    return word[:-1]


# Question words that would match almost every row, so "nothing found" could never happen.
# Stemmed like every other token, so "payments" and "payment" are both dropped.
STOP_WORDS = frozenset(
    stem(word)
    for word in """
    a about all an and any are at be by can did do does done ever for from get got had has have
    how i in is it last list many me money much my of on or our paid pay payment payments show
    spend spending spent that the there this time times to total transaction transactions was we
    were what when where which who with
    """.split()
)


# --- Pure functions ------------------------------------------------------------------------------


def tokenize(text: str) -> list[str]:
    """Lower-case, stemmed words: the analyzer for both BM25 documents and the question."""
    return [stem(token) for token in _TOKEN.findall(text.lower())]


def remove_stopwords(tokens: list[str]) -> list[str]:
    return [token for token in tokens if token not in STOP_WORDS]


def bm25_scores(query: list[str], corpus: list[list[str]]) -> np.ndarray:
    """Okapi BM25 score of every document for the query (rank-bm25). It builds its index on
    each call, about 15 ms of CPU at 8k rows. Scores only order rows: whether a row matches
    is `keyword_presence`, because BM25's IDF can go negative on very small corpora."""
    if not query or not corpus:
        return np.zeros(len(corpus))
    return BM25Okapi(corpus).get_scores(query)


def keyword_presence(query: list[str], corpus: list[list[str]]) -> np.ndarray:
    """True where a document contains at least one query term: a keyword match."""
    terms = set(query)
    return np.array([not terms.isdisjoint(tokens) for tokens in corpus], dtype=bool)


def unit_query(vector) -> np.ndarray:
    """The question vector as a new float32 array of length 1."""
    try:
        query = np.asarray(vector, dtype=np.float32)
    except (TypeError, ValueError):
        query = np.zeros(0, dtype=np.float32)
    norm = np.linalg.norm(query) if query.ndim == 1 and query.size else 0.0
    if norm == 0 or not np.isfinite(norm):
        raise RagError("invalid_vector", "The question vector must be finite and not all zeros.")
    return query / norm


def cosine_scores(query: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    """Exact cosine similarity of every row to the query, what FAISS's IndexFlat does.

    Rows are stored at length 1, so this is a dot product with the normalised query. float16
    rows are widened in chunks: numpy's float16 maths is slow, and the whole matrix at float32
    would double the memory.
    """
    query = unit_query(query)
    scores = np.empty(len(matrix), dtype=np.float32)
    for start in range(0, len(matrix), COSINE_CHUNK):
        chunk = matrix[start : start + COSINE_CHUNK]
        scores[start : start + len(chunk)] = chunk.astype(np.float32) @ query
    return scores


def rank(scores: np.ndarray, mask: np.ndarray, limit: int) -> list[int]:
    """Indexes where `mask` is true, best score first, at most `limit`."""
    hits = np.flatnonzero(mask)
    order = np.argsort(-scores[hits], kind="stable")  # stable: ties keep the newest-first order
    return hits[order][:limit].tolist()


def vector_matches(scores: np.ndarray, profile: Profile, margin: float) -> np.ndarray:
    """Which rows count as vector matches.

    A tuned profile has a threshold tuned for that model. An untuned model's scale is unknown, so
    rows within `margin` of the best score count; that rule can't say "nothing found" by itself,
    so an untuned model always returns its closest rows.
    """
    if not len(scores):
        return np.zeros(0, dtype=bool)
    if profile.tuned:
        return scores >= profile.min_similarity
    return scores >= scores.max() - margin


def rrf_fuse(rankings: list[list[int]], k: int, limit: int) -> list[tuple[int, float]]:
    """Reciprocal rank fusion: each list adds 1 / (k + rank) for every row it ranks.

    Rows ranked well by either list rise, rows ranked by both rise most, and raw scores are
    ignored, so BM25 and cosine never need calibrating against each other. k = 60 is the value
    from the original paper (Cormack et al., 2009) and what Elastic and Azure AI Search use.
    """
    fused: dict[int, float] = {}
    for ranking in rankings:
        for position, index in enumerate(ranking, start=1):
            fused[index] = fused.get(index, 0.0) + 1.0 / (k + position)
    best = sorted(fused.items(), key=lambda item: (-item[1], item[0]))
    return best[:limit]


def keyword_ranking(
    query: list[str], corpus: list[list[str]], limit: int
) -> tuple[list[int], np.ndarray]:
    """The keyword side of a search: (matching rows best first, every row's BM25 score)."""
    scores = bm25_scores(query, corpus)
    return rank(scores, keyword_presence(query, corpus), limit), scores


def vector_ranking(
    query: np.ndarray, matrix: np.ndarray, profile: Profile, margin: float, limit: int
) -> tuple[list[int], np.ndarray]:
    """The vector side of a search: (matching rows best first, every row's cosine score)."""
    scores = cosine_scores(query, matrix)
    return rank(scores, vector_matches(scores, profile, margin), limit), scores


def validate_ask_filters(raw) -> dict:
    """The ask's own filters: {"date": a dashboard date filter, "type": "credit" | "debit" | None,
    "data_sources": [ids], empty for all of them}.

    Defaults to all time; "inherit" has no dashboard to inherit from, so it means all time.
    """
    raw = raw or {}
    if not isinstance(raw, dict) or set(raw) - {"date", "type", "data_sources"}:
        raise RagError("invalid_filters", "filters may only contain date, type and data_sources.")
    sources = raw.get("data_sources") or []
    try:
        if not isinstance(sources, list) or len(sources) > MAX_DATA_SOURCES:
            raise ValueError
        sources = [uuid.UUID(item) for item in sources]
    except (ValueError, TypeError, AttributeError):
        raise RagError("invalid_filters", "filters.data_sources must list data source ids.") from None
    try:
        date_filter = validate_date_filter(raw.get("date") or {"preset": "all"})
    except SpecError as problem:
        raise RagError("invalid_filters", problem.detail) from None
    if date_filter["preset"] == "inherit":
        date_filter = {"preset": "all"}
    txn_type = raw.get("type")
    if txn_type is not None and txn_type not in TXN_TYPES:
        raise RagError("invalid_filters", "filters.type must be credit or debit.")
    return {"date": date_filter, "type": txn_type, "data_sources": sources}


@contextmanager
def gc_paused():
    """No cyclic garbage collection during one search.

    A search makes ~100k short-lived objects (token lists, BM25's dicts), and every collection
    they trigger walks the worker's whole heap: at 0.1 CPU that cost whole 100 ms scheduler
    periods. None of them form cycles, so reference counting frees them all anyway.
    """
    was_enabled = gc.isenabled()
    gc.disable()
    try:
        yield
    finally:
        if was_enabled:
            gc.enable()


class _Stopwatch:
    """Milliseconds per stage, wall and CPU, for the log line and the performance test."""

    def __init__(self):
        self.ms: dict[str, float] = {}
        self.cpu_ms: dict[str, float] = {}

    @contextmanager
    def stage(self, name: str):
        wall, cpu = time.perf_counter(), time.process_time()
        try:
            yield
        finally:
            self.ms[name] = round((time.perf_counter() - wall) * 1000, 1)
            self.cpu_ms[name] = round((time.process_time() - cpu) * 1000, 1)


# --- Database ------------------------------------------------------------------------------------

_DOCS = RagDocument._meta.db_table
_TXNS = Transaction._meta.db_table
_CATEGORIES = Category._meta.db_table


def _fetch_binary(sql: str, params: list) -> list[tuple]:
    """Rows with bytea in binary form, on Django's own connection and transaction.

    Django's cursor binds parameters client-side, and psycopg can then only return text, where
    bytea arrives hex-encoded: twice the bytes from Neon and decoding work on our 0.1 CPU (binary
    halves the SQL stage's CPU). The query is still fully parameterised. Being a plain psycopg
    cursor, it bypasses Django's query hooks (DEBUG query log, execute_wrapper).
    """
    connection.ensure_connection()
    with psycopg.Cursor(connection.connection) as cursor:
        cursor.execute(sql, params, binary=True)
        return cursor.fetchall()


def _where(user, model: str, digest: str, dims: int, start: date, end: date, txn_type, sources):
    clauses = [
        "d.user_id = %s", "t.user_id = %s", "d.model = %s", "d.model_digest = %s",
        "d.dims = %s", "d.text_version = %s", "t.date BETWEEN %s AND %s",
    ]  # fmt: skip
    params = [user.id, user.id, model, digest, dims, TEXT_VERSION, start, end]
    if txn_type:
        clauses.append("t.txn_type = %s")
        params.append(txn_type)
    if sources:
        clauses.append("t.data_source_id = ANY(%s)")
        params.append(sources)
    return " AND ".join(clauses), params


# --- The retriever -------------------------------------------------------------------------------


@dataclass
class SearchResult:
    documents: list[Document]
    period: dict  # {"from", "to", "source": "question" | "filter", "phrase"}
    coverage: dict  # {"searched", "indexed", "total"} in the period
    stats: dict = field(default_factory=dict)  # counts and timings only, never content


class EncryptedHybridRetriever(BaseRetriever):
    """A LangChain retriever over one user's encrypted index.

    A vector database is one implementation of the retriever interface; this is an encrypted,
    exact-search implementation of the same interface. The scope comes from the request's user,
    never from the model or the question.
    """

    user: Any
    model: str
    digest: str
    query_vector: list[float]
    filters: dict | None = None  # raw; validated by validate_ask_filters (None: all time)
    use_question_period: bool = True
    today: date | None = None

    def _get_relevant_documents(
        self, query: str, *, run_manager: CallbackManagerForRetrieverRun
    ) -> list[Document]:
        return self.search(query).documents

    def search(self, question: str) -> SearchResult:
        with gc_paused():
            return self._search(question)

    def _search(self, question: str) -> SearchResult:
        today = self.today or timezone.localdate()
        filters = validate_ask_filters(self.filters)
        query_vector = unit_query(self.query_vector)  # refuse a bad vector before any SQL
        date_filter, detected = self._date_filter(question, filters["date"], today)
        start, end = resolve_period(date_filter, date_filter, today)
        txn_type, sources = filters["type"], filters["data_sources"]
        # The question's size goes straight into the WHERE clause, so a normal search makes no
        # extra round trip to look the size up; _explain_empty runs only when nothing came back.
        dims = len(query_vector)
        watch = _Stopwatch()

        where, params = _where(
            self.user, self.model, self.digest, dims, start, end, txn_type, sources
        )
        with watch.stage("sql"):
            rows = _fetch_binary(
                f"SELECT d.transaction_id, d.payload_enc, c.name FROM {_DOCS} d "
                f"JOIN {_TXNS} t ON t.id = d.transaction_id "
                f"JOIN {_CATEGORIES} c ON c.id = t.category_id "
                f"WHERE {where} ORDER BY t.date DESC, t.created_at DESC, t.id LIMIT %s",
                [*params, settings.RAG_MAX_DOCS],
            )
        if not rows:
            self._explain_empty(dims)
        with watch.stage("counts"):
            coverage, first = self._coverage(
                len(rows), where, params, start, end, txn_type, sources
            )
        with watch.stage("decrypt"):
            cipher = UserCipher(self.user)
            payloads = [cipher.decrypt(blob, DOC_CONTEXT) for _, blob, _ in rows]
        with watch.stage("unpack"):
            matrix, texts = codec.unpack_many(payloads, dims)
            del payloads
        with watch.stage("tokens"):
            corpus = [tokenize(f"{text} {row[2]}") for text, row in zip(texts, rows)]
            keyword_text = detected.remainder if detected else question
            query = remove_stopwords(tokenize(keyword_text))
        limit = settings.RAG_MAX_MATCHES
        with watch.stage("bm25"):
            keyword, bm25 = keyword_ranking(query, corpus, limit)
        with watch.stage("cosine"):
            profile = profile_for(self.model)
            vector, cosine = vector_ranking(
                query_vector, matrix, profile, settings.RAG_RELATIVE_MARGIN, limit
            )
        with watch.stage("fuse"):
            fused = rrf_fuse([keyword, vector], settings.RAG_RRF_K, limit)
            documents = [
                Document(
                    page_content=texts[index],
                    metadata={
                        "transaction": str(rows[index][0]),
                        "rrf": round(score, 6),
                        "bm25": round(float(bm25[index]), 4),
                        "cosine": round(float(cosine[index]), 4),
                    },
                )
                for index, score in fused
            ]

        if (
            start == MIN_DATE
        ):  # "all": from the first transaction in the period, like the dashboards
            start = min(first, end) if first else end
        period = {
            "from": start.isoformat(),
            "to": end.isoformat(),
            "source": "question" if detected else "filter",
            "phrase": detected.phrase if detected else None,
        }
        stats = {
            "documents": len(rows),
            "keyword": len(keyword),
            "vector": len(vector),
            "matches": len(documents),
            "ms": watch.ms,
            "cpu_ms": watch.cpu_ms,
        }
        return SearchResult(documents, period, coverage, stats)

    def _date_filter(self, question: str, chosen: dict, today: date):
        """The period to search: a date phrase in the question wins over the select,
        unless the user removed its chip. Returns (date filter, DetectedPeriod or None)."""
        detected = detect_period(question, today) if self.use_question_period else None
        return (detected.date_filter if detected else chosen), detected

    def _explain_empty(self, dims: int) -> None:
        """Nothing came back: say why if it's the index, not the period, that's missing."""
        stored = (
            RagDocument.objects.filter(user=self.user, model=self.model, model_digest=self.digest)
            .values_list("dims", flat=True)
            .first()
        )
        if stored is None:
            raise RagError("no_index", "Nothing is indexed with this model yet.")
        if stored != dims:
            raise RagError(
                "dimension_mismatch",
                f"The question vector has {dims} dimensions; the index has {stored}.",
            )

    def _coverage(
        self,
        searched: int,
        where: str,
        params: list,
        start: date,
        end: date,
        txn_type: str | None,
        sources: list,
    ) -> tuple[dict, date | None]:
        """How much of the period was searched, and its first transaction's date.

        `searched < indexed` shows the cap (RAG_MAX_DOCS); `indexed < total` shows rows not
        embedded yet. The total and the first date come from one aggregate query, and the
        indexed count needs a query only when the cap was hit.
        """
        if searched < settings.RAG_MAX_DOCS:
            indexed = searched
        else:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT count(*) FROM {_DOCS} d JOIN {_TXNS} t ON t.id = d.transaction_id "
                    f"WHERE {where}",
                    params,
                )
                (indexed,) = cursor.fetchone()
        in_period = Transaction.objects.filter(user=self.user, date__range=(start, end))
        if txn_type:
            in_period = in_period.filter(txn_type=txn_type)
        if sources:
            in_period = in_period.filter(data_source_id__in=sources)
        totals = in_period.aggregate(total=Count("id"), first=Min("date"))
        coverage = {"searched": searched, "indexed": indexed, "total": totals["total"]}
        return coverage, totals["first"]

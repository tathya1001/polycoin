"""What the panel builder knows about one user, and how it matches the user's words to it.

The model only ever sees the user's own request and category names. Matching a phrase to a
category or a merchant happens here, in code, against the user's own data: categories by name,
stem, keyword or spelling; merchants by the names on the user's newest transactions. A merchant
that matches no name can fall back to the "Ask" search index, by meaning.
"""

import difflib
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from django.conf import settings
from django.utils import timezone

from categories.models import Category, CategoryKeyword
from insights.services import first_transaction_date
from insights.spec import MAX_MERCHANT_LENGTH
from transactions.models import Transaction
from vault.services import UserCipher

from ..models import RagDocument
from ..rag.errors import RagError
from ..rag.profiles import TEXT_VERSION
from ..rag.retriever import EncryptedHybridRetriever, tokenize

FUZZY_CUTOFF = 0.8  # difflib ratio: catches a typo ("grocries"), not a different word
MEANING_TOP_K = 5  # search matches that vote on a merchant found by meaning
# A shorter phrase ("a") is part of almost every name, so it would filter by nothing useful.
MIN_MERCHANT_PHRASE = 2


def normal_merchant(name: str) -> str:
    """A merchant name as the charts group it (insights.engine.dimension_key)."""
    return " ".join(name.split()).title()


def _stemmed(text: str) -> str:
    """The text's words, stemmed: "Groceries" and "grocery" give the same key."""
    return " ".join(tokenize(text))


@dataclass(frozen=True)
class CategoryRef:
    id: str
    name: str


@dataclass(frozen=True)
class CategoryMatch:
    category: CategoryRef
    how: str  # "name", "stem", "keyword" or "spelling"


class CategoryIndex:
    """The user's categories and keywords, matched in a fixed order: exact name (names are
    unique per user, ignoring case), then the stemmed name, then a keyword, then a near spelling."""

    def __init__(self, categories: list[CategoryRef], keywords: list[tuple[str, str]]):
        self.categories = categories
        by_id = {ref.id: ref for ref in categories}
        self._by_name = {ref.name.lower(): ref for ref in categories}
        self._by_stem = {_stemmed(ref.name): ref for ref in categories}
        self._by_keyword = {}
        for term, category_id in keywords:  # (term, category id)
            for key in (term.lower(), _stemmed(term)):
                self._by_keyword.setdefault(key, by_id[category_id])

    @property
    def names(self) -> list[str]:
        return [ref.name for ref in self.categories]

    def match(self, phrase: str) -> CategoryMatch | None:
        lowered = " ".join(phrase.lower().split())
        if not lowered:
            return None
        if lowered in self._by_name:
            return CategoryMatch(self._by_name[lowered], "name")
        stemmed = _stemmed(lowered)
        if stemmed and stemmed in self._by_stem:
            return CategoryMatch(self._by_stem[stemmed], "stem")
        for key in (lowered, stemmed):
            if key in self._by_keyword:
                return CategoryMatch(self._by_keyword[key], "keyword")
        close = difflib.get_close_matches(lowered, list(self._by_name), n=1, cutoff=FUZZY_CUTOFF)
        if close:
            return CategoryMatch(self._by_name[close[0]], "spelling")
        return None


@dataclass
class AgentContext:
    """Facts for one request, built per request from the database. Passed to the graph as its
    runtime context, which is never stored in the agent state or the token."""

    user: Any
    today: date
    categories: CategoryIndex
    first_date: date | None  # the user's oldest transaction, for the "all" period
    embed: dict | None = None  # {"model", "digest"} when that model's search index exists
    # The turn's result, set by the graph's last node and read by the caller. It holds the
    # preview's chart data, which must not go into the token.
    outcome: dict | None = None
    _merchants: list[str] | None = field(default=None, repr=False)

    def merchant_names(self) -> list[str]:
        """Loaded on first use only: most requests name no merchant."""
        if self._merchants is None:
            self._merchants = merchant_names(self.user)
        return self._merchants


def rag_available(user, model: str, digest: str) -> bool:
    """True if the user has search documents for this embedding model and version."""
    return RagDocument.objects.filter(
        user=user, model=model, model_digest=digest, text_version=TEXT_VERSION
    ).exists()


def build_context(user, today: date | None = None, embed: dict | None = None) -> AgentContext:
    """Two small queries for categories and keywords, one for the first date. `embed` is the
    browser's embedding model ({"model", "digest"}); it is kept only if its index exists."""
    categories = [
        CategoryRef(str(pk), name)
        for pk, name in Category.objects.filter(user=user).values_list("id", "name")
    ]
    keywords = [
        (term, str(category_id))
        for term, category_id in CategoryKeyword.objects.filter(category__user=user).values_list(
            "term", "category_id"
        )
    ]
    if embed and not rag_available(user, embed["model"], embed["digest"]):
        embed = None
    return AgentContext(
        user=user,
        today=today or timezone.localdate(),
        categories=CategoryIndex(categories, keywords),
        first_date=first_transaction_date(user),
        embed=embed,
    )


def merchant_names(user, limit: int | None = None) -> list[str]:
    """The user's distinct merchants, newest first, from at most `limit` transactions.

    Names are encrypted, so finding one means decrypting them; the cap bounds that work. One
    cipher (one key load) serves every row."""
    limit = settings.AGENT_MERCHANT_SCAN if limit is None else limit
    blobs = (
        Transaction.objects.filter(user=user)
        .order_by("-date", "-created_at")
        .values_list("name_enc", flat=True)[:limit]
    )
    cipher = UserCipher(user)
    names = (normal_merchant(cipher.decrypt(bytes(blob), "txn.name").decode()) for blob in blobs)
    return list(dict.fromkeys(name for name in names if name))


@dataclass(frozen=True)
class MerchantMatch:
    contains: str  # the text a panel's merchant filter looks for in each name
    how: str  # "name", "spelling" or "meaning"
    matches: int  # how many of the user's merchants the filter covers


def match_merchant(phrase: str, names: list[str]) -> MerchantMatch | None:
    """The user's phrase against their merchant names: a part of a name first ("tasty" covers
    "Tastybites Cafe" and "Tastybites Kitchen", as the filter will), then a near spelling."""
    wanted = " ".join(phrase.lower().split())
    if len(wanted) < MIN_MERCHANT_PHRASE:
        return None
    lowered = [name.lower() for name in names]
    hits = sum(wanted in name for name in lowered)
    if hits:
        return MerchantMatch(wanted, "name", hits)
    close = difflib.get_close_matches(wanted, lowered, n=1, cutoff=FUZZY_CUTOFF)
    if close:
        return MerchantMatch(close[0][:MAX_MERCHANT_LENGTH], "spelling", 1)
    return None


def merchant_by_meaning(
    ctx: AgentContext, phrase: str, vector: list[float]
) -> MerchantMatch | None:
    """The merchant the "Ask" index finds closest to the phrase, or None.

    `vector` is the phrase as the browser embedded it with ctx.embed's model. The most common
    merchant among the top matches wins, so one stray row cannot decide it. Every period is
    searched, and the phrase's own words never narrow the period.
    """
    if not ctx.embed:
        return None
    try:
        result = EncryptedHybridRetriever(
            user=ctx.user,
            model=ctx.embed["model"],
            digest=ctx.embed["digest"],
            query_vector=vector,
            use_question_period=False,
            today=ctx.today,
        ).search(phrase)
    except RagError:
        return None  # a vector of the wrong size, or an index that changed: no match
    ids = [doc.metadata["transaction"] for doc in result.documents[:MEANING_TOP_K]]
    if not ids:
        return None
    cipher = UserCipher(ctx.user)
    blobs = dict(
        Transaction.objects.filter(user=ctx.user, id__in=ids).values_list("id", "name_enc")
    )
    names = [
        normal_merchant(cipher.decrypt(bytes(blobs[pk]), "txn.name").decode())
        for pk in map(uuid.UUID, ids)
        if pk in blobs
    ]
    # Counted in ranking order, so a tie goes to the merchant the search ranked first.
    votes = Counter(name for name in names if name)
    if not votes:
        return None
    name = votes.most_common(1)[0][0]
    return MerchantMatch(name.lower()[:MAX_MERCHANT_LENGTH], "meaning", 1)

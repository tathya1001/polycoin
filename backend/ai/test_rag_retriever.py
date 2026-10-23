import gc
from datetime import date

import numpy as np
import pytest
from langchain_core.documents import Document

from ai.rag import index, retriever
from ai.rag.errors import RagError
from ai.rag.profiles import Profile
from ai.rag.retriever import (
    EncryptedHybridRetriever,
    bm25_scores,
    cosine_scores,
    keyword_presence,
    rank,
    remove_stopwords,
    rrf_fuse,
    tokenize,
    unit_query,
    validate_ask_filters,
    vector_matches,
)
from categories.models import Category
from transactions.tests import make_txn, make_user

TODAY = date(2026, 2, 10)
MODEL, DIGEST = "test-embed:latest", "sha256:aaaa"  # no profile: untuned, no prefixes

# --- pure functions ----------------------------------------------------------------


def test_tokenize_keeps_letters_and_digits_in_any_script():
    assert tokenize("Café_Bar UPI/412 ₹ FITZONE-gym") == [
        "café",
        "bar",
        "upi",
        "412",
        "fitzone",
        "gym",
    ]


def test_remove_stopwords_keeps_only_the_words_that_carry_meaning():
    tokens = tokenize("How much did I spend at the gym last month?")
    assert remove_stopwords(tokens) == ["gym", "month"]


def test_keyword_presence_means_at_least_one_query_term():
    corpus = [["fitzone", "gym"], ["tastybites", "cafe"], ["gym", "cafe"]]
    assert keyword_presence(["gym"], corpus).tolist() == [True, False, True]
    assert keyword_presence([], corpus).tolist() == [False, False, False]


def test_bm25_ranks_a_repeated_term_higher_and_is_zero_without_a_query():
    corpus = [["gym", "gym", "fitzone"], ["gym", "cafe"], ["cafe"], ["rent"], ["fuel"], ["tea"]]
    scores = bm25_scores(["gym"], corpus)
    assert scores[0] > scores[1] > 0 and not scores[2:].any()
    assert bm25_scores([], corpus).tolist() == [0] * 6
    assert bm25_scores(["gym"], []).tolist() == []


def test_a_term_in_half_the_rows_scores_zero_so_presence_decides_a_match():
    # Okapi IDF is log((N - n + 0.5) / (n + 0.5)): 0 when a term is in half of N rows, and below
    # 0 when in more. That's why a keyword match is "the term is present", not "BM25 > 0".
    corpus = [["gym"], ["gym", "cafe"], ["cafe"], ["rent"]]
    assert not bm25_scores(["gym"], corpus).any()
    assert keyword_presence(["gym"], corpus).tolist() == [True, True, False, False]


def test_cosine_scores_are_exact_and_do_not_depend_on_the_chunk_size(monkeypatch):
    rng = np.random.default_rng(1)
    matrix = rng.standard_normal((7, 16))
    matrix = (matrix / np.linalg.norm(matrix, axis=1, keepdims=True)).astype(np.float16)
    query = rng.standard_normal(16)

    expected = matrix.astype(np.float64) @ (query / np.linalg.norm(query))
    assert cosine_scores(query, matrix) == pytest.approx(expected, abs=1e-5)
    monkeypatch.setattr(retriever, "COSINE_CHUNK", 3)  # 7 rows: chunks of 3, 3 and 1
    assert cosine_scores(query, matrix) == pytest.approx(expected, abs=1e-5)


def test_cosine_scores_leave_the_callers_vector_alone():
    query = np.array([3.0, 4.0], dtype=np.float32)
    cosine_scores(query, np.array([[1.0, 0.0]], dtype=np.float16))
    assert query.tolist() == [3.0, 4.0]


@pytest.mark.parametrize("bad", [[0.0, 0.0], [1.0, float("nan")], [], [[1.0]], "x", None])
def test_a_question_vector_must_be_finite_and_not_all_zeros(bad):
    with pytest.raises(RagError) as error:
        unit_query(bad)
    assert error.value.code == "invalid_vector"


def test_rank_keeps_only_masked_rows_best_first_with_stable_ties():
    scores = np.array([0.5, 0.9, 0.5, 0.1])
    assert rank(scores, np.array([True, True, True, False]), 10) == [1, 0, 2]
    assert rank(scores, np.array([True, True, True, True]), 2) == [1, 0]


def test_a_tuned_profile_matches_by_its_threshold():
    profile = Profile("", "", min_similarity=0.5)
    assert vector_matches(np.array([0.2, 0.5, 0.7]), profile, 0.05).tolist() == [False, True, True]
    assert not vector_matches(np.array([0.1, 0.2]), profile, 0.05).any()  # can say "nothing"


def test_an_untuned_profile_matches_rows_near_the_best_score():
    scores = np.array([0.30, 0.71, 0.74, 0.60])
    assert vector_matches(scores, Profile("", ""), 0.05).tolist() == [False, True, True, False]
    assert vector_matches(np.zeros(0), Profile("", ""), 0.05).tolist() == []


def test_rrf_puts_a_row_both_lists_found_first():
    fused = rrf_fuse([[3, 1, 2], [1, 4]], k=60, limit=10)
    assert [index for index, _ in fused] == [1, 3, 4, 2]
    assert fused[0][1] == pytest.approx(1 / 62 + 1 / 61)
    assert rrf_fuse([[3, 1, 2], [1, 4]], k=60, limit=2) == fused[:2]
    assert rrf_fuse([[], []], k=60, limit=10) == []


def test_rrf_breaks_a_tie_by_row_order_so_newer_rows_win():
    assert [index for index, _ in rrf_fuse([[5], [2]], k=60, limit=10)] == [2, 5]


@pytest.mark.parametrize(
    "raw, expected",
    [
        (None, {"date": {"preset": "all"}, "type": None}),
        ({}, {"date": {"preset": "all"}, "type": None}),
        ({"date": {"preset": "inherit"}}, {"date": {"preset": "all"}, "type": None}),
        (
            {"date": {"preset": "last_month"}, "type": "debit"},
            {"date": {"preset": "last_month"}, "type": "debit"},
        ),
    ],
)
def test_ask_filters_default_to_all_time(raw, expected):
    assert validate_ask_filters(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        {"merchant_contains": "x"},
        {"type": "refund"},
        {"date": {"preset": "someday"}},
        {"date": {"preset": "custom", "from": "2026-02-10", "to": "2026-01-01"}},
        ["not", "a", "dict"],
    ],
)
def test_bad_ask_filters_are_refused(raw):
    with pytest.raises(RagError) as error:
        validate_ask_filters(raw)
    assert error.value.code == "invalid_filters"


# --- search over a real encrypted index --------------------------------------------

# Each fictional merchant gets its own direction, so the vector side is predictable.
VECTORS = {
    "Fitzone": [1.0, 0.0, 0.0, 0.0],
    "Tastybites": [0.0, 1.0, 0.0, 0.0],
    "Maple": [0.0, 0.0, 1.0, 0.0],
    "Acme": [0.0, 0.0, 0.0, 1.0],
}
NEAR_GYM = [0.9, 0.1, 0.0, 0.0]
NEAR_RENT = [0.0, 0.1, 0.9, 0.0]


def category(user, name):
    return Category.objects.get(user=user, name=name)


def history(user):
    """Five rows (newest first: cafe, salary, gym, rent, older gym), indexed with VECTORS."""
    rows = {
        "cafe": make_txn(user, name="Tastybites Cafe", description="UPI/TASTYBITES/lunch",
                         date=date(2026, 2, 1), category=category(user, "Food")),
        "salary": make_txn(user, name="Acme Payroll", description="NEFT/ACME/jan", txn_type="credit",
                           date=date(2026, 1, 31), category=category(user, "Salary")),
        "gym": make_txn(user, name="Fitzone Gym", description="UPI/FITZONE/jan",
                        date=date(2026, 1, 5), category=category(user, "Health")),
        "rent": make_txn(user, name="Maple Street Homes", description="NEFT/MAPLE/dec",
                         date=date(2025, 12, 3), category=category(user, "Rent")),
        "old_gym": make_txn(user, name="Fitzone Gym", description="UPI/FITZONE/nov",
                            date=date(2025, 11, 5), category=category(user, "Health")),
    }  # fmt: skip
    batch = index.pending(user, MODEL, DIGEST, 100)
    items = [
        {**item, "vector": next(v for name, v in VECTORS.items() if name in item["text"])}
        for item in batch["items"]
    ]
    assert index.store_vectors(user, MODEL, DIGEST, items)["stored"] == 5
    return rows


def search(user, question, vector=NEAR_GYM, **fields):
    found = EncryptedHybridRetriever(
        user=user, model=MODEL, digest=DIGEST, query_vector=vector, today=TODAY, **fields
    )
    return found.search(question)


def ids(result):
    return [doc.metadata["transaction"] for doc in result.documents]


@pytest.fixture
def alice(db):
    return make_user("alice@example.com")


@pytest.fixture
def rows(alice):
    return history(alice)


def test_keywords_and_vectors_agree_on_the_gym(alice, rows):
    result = search(alice, "What do I pay for the gym?")

    assert ids(result)[:2] == [str(rows["gym"].id), str(rows["old_gym"].id)]
    top = result.documents[0]
    assert isinstance(top, Document) and top.page_content.startswith("Fitzone Gym")
    assert set(top.metadata) == {"transaction", "rrf", "bm25", "cosine"}
    assert top.metadata["bm25"] > 0 and top.metadata["cosine"] == pytest.approx(0.994, abs=1e-3)


def test_a_keyword_finds_what_the_vector_missed_and_the_other_way_round(alice, rows):
    result = search(alice, "tastybites", vector=NEAR_RENT)
    assert set(ids(result)) == {str(rows["cafe"].id), str(rows["rent"].id)}


def test_the_category_name_is_searchable_without_being_in_the_text(alice, rows):
    result = search(alice, "food", vector=NEAR_RENT)
    assert str(rows["cafe"].id) in ids(result)  # the live category name, not the vector


def test_a_question_of_only_stop_words_falls_back_to_vectors(alice, rows):
    result = search(alice, "how much did I spend?", vector=NEAR_RENT)
    assert result.stats["keyword"] == 0
    assert ids(result) == [str(rows["rent"].id)]


def test_a_tuned_threshold_can_find_nothing(alice, rows, monkeypatch):
    monkeypatch.setattr(retriever, "profile_for", lambda model: Profile("", "", 0.99))
    result = search(alice, "how much did I spend?", vector=[0.5, 0.5, 0.5, 0.5])
    assert result.documents == [] and result.stats["matches"] == 0


def test_a_date_phrase_in_the_question_sets_the_period(alice, rows):
    result = search(alice, "gym last month")

    assert ids(result) == [str(rows["gym"].id)]  # January only; November's gym is outside
    assert result.period == {
        "from": "2026-01-01",
        "to": "2026-01-31",
        "source": "question",
        "phrase": "last month",
    }


def test_removing_the_chip_searches_the_selected_period_instead(alice, rows):
    result = search(
        alice,
        "gym last month",
        use_question_period=False,
        filters={"date": {"preset": "custom", "from": "2025-11-01", "to": "2025-11-30"}},
    )
    assert ids(result) == [str(rows["old_gym"].id)]
    assert result.period["source"] == "filter" and result.period["phrase"] is None


def test_all_time_starts_at_the_first_transaction(alice, rows):
    assert search(alice, "gym").period["from"] == "2025-11-05"


def test_the_type_filter_runs_in_sql(alice, rows):
    result = search(alice, "acme payroll", filters={"type": "debit"})
    assert str(rows["salary"].id) not in ids(result)
    assert result.coverage == {"searched": 4, "indexed": 4, "total": 4}


def test_only_the_users_own_documents_are_searched(alice, rows):
    bob = make_user("bob@example.com")
    history(bob)
    result = search(alice, "gym")
    assert set(ids(result)) <= {str(row.id) for row in rows.values()}
    assert result.coverage["searched"] == 5


def test_the_cap_searches_the_newest_documents_and_says_so(alice, rows, settings):
    settings.RAG_MAX_DOCS = 3
    result = search(alice, "gym")

    assert str(rows["old_gym"].id) not in ids(result)  # the oldest is past the cap
    assert result.coverage == {"searched": 3, "indexed": 5, "total": 5}


def test_coverage_counts_rows_not_indexed_yet(alice, rows):
    make_txn(alice, name="New Row", description="UPI/NEW/x", date=date(2026, 2, 5))
    assert search(alice, "gym").coverage == {"searched": 5, "indexed": 5, "total": 6}


def test_stats_hold_counts_and_timings_but_no_text(alice, rows):
    stats = search(alice, "gym").stats
    assert set(stats) == {"documents", "keyword", "vector", "matches", "ms", "cpu_ms"}
    assert set(stats["ms"]) == {
        "sql",
        "counts",
        "decrypt",
        "unpack",
        "tokens",
        "bm25",
        "cosine",
        "fuse",
    }
    assert "Fitzone" not in repr(stats) and "gym" not in repr(stats)


def test_garbage_collection_is_back_on_after_a_search(alice, rows):
    search(alice, "gym")
    assert gc.isenabled()


def test_it_works_through_langchains_retriever_interface(alice, rows):
    found = EncryptedHybridRetriever(
        user=alice, model=MODEL, digest=DIGEST, query_vector=NEAR_GYM, today=TODAY
    )
    documents = found.invoke("gym")
    assert documents[0].metadata["transaction"] == str(rows["gym"].id)


def test_no_index_for_the_model_is_refused(alice, rows):
    with pytest.raises(RagError) as error:
        EncryptedHybridRetriever(
            user=alice, model="other-model", digest=DIGEST, query_vector=NEAR_GYM, today=TODAY
        ).search("gym")
    assert error.value.code == "no_index"


def test_a_question_vector_of_another_size_is_refused(alice, rows):
    with pytest.raises(RagError) as error:
        search(alice, "gym", vector=[1.0, 0.0, 0.0])
    assert error.value.code == "dimension_mismatch"


def test_a_period_with_no_documents_is_an_empty_result_not_an_error(alice, rows):
    result = search(
        alice,
        "gym",
        filters={"date": {"preset": "custom", "from": "2024-01-01", "to": "2024-01-31"}},
    )
    assert result.documents == []
    assert result.coverage == {"searched": 0, "indexed": 0, "total": 0}
    assert result.period["from"] == "2024-01-01"

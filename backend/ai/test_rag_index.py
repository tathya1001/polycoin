import logging
from datetime import date

import numpy as np
import pytest

from ai.models import RagDocument
from ai.rag import codec, index
from ai.rag.errors import RagError
from ai.scoring import prepare_text
from categories.models import Category
from transactions.tests import make_txn, make_user
from vault.services import UserCipher

pytestmark = pytest.mark.django_db

MODEL, DIGEST = "nomic-embed-text:latest", "sha256:aaaa"


@pytest.fixture
def alice():
    return make_user("alice@example.com")


@pytest.fixture
def bob():
    return make_user("bob@example.com")


def txns(user, count):
    """`count` rows, the newest last; every one distinct, so fingerprints never collide."""
    return [
        make_txn(user, name=f"Shop{n}", description=f"UPI/SHOP{n}/x", date=date(2026, 1, 1 + n))
        for n in range(count)
    ]


def vector(dims=4, seed=0):
    return np.random.default_rng(seed).standard_normal(dims).tolist()


def embed(items, dims=4):
    """What the browser sends back after embedding a pending batch."""
    return [
        {"transaction": item["transaction"], "version": item["version"], "vector": vector(dims, n)}
        for n, item in enumerate(items)
    ]


def index_all(user, model=MODEL, digest=DIGEST):
    batch = index.pending(user, model, digest, 100)
    return index.store_vectors(user, model, digest, embed(batch["items"]))


def stored(txn):
    doc = RagDocument.objects.get(transaction=txn)
    vec, text = codec.unpack(UserCipher(txn.user).decrypt(bytes(doc.payload_enc), "rag.doc"))
    return doc, vec, text


def set_name(txn, name):
    txn.name_enc = UserCipher(txn.user).encrypt(name.encode(), "txn.name")
    txn.save()


# --- document_text ----------------------------------------------------------------


def test_the_document_text_is_prepare_text_of_name_notes_and_description(alice):
    txn = make_txn(alice, name="FITZONE", description="UPI/DR/412345678901/FITZONE/fit@okbank")
    txn.notes_enc = UserCipher(alice).encrypt(b"gym membership", "txn.notes")
    txn.save()

    text = index.document_text(UserCipher(alice), txn)

    assert text == prepare_text(
        "FITZONE", "UPI/DR/412345678901/FITZONE/fit@okbank", "gym membership"
    )
    assert "gym membership" in text and "412345678901" not in text


# --- pending ----------------------------------------------------------------------


def test_pending_hands_out_new_rows_newest_first_with_the_document_prefix(alice):
    rows = txns(alice, 3)

    batch = index.pending(alice, MODEL, DIGEST, 10)

    assert [item["transaction"] for item in batch["items"]] == [str(t.id) for t in rows[::-1]]
    assert batch["items"][0]["text"] == "search_document: Shop2 x"
    assert batch["items"][0]["version"] == rows[2].updated_at.isoformat()
    assert batch["remaining"] == 0


def test_a_model_without_a_profile_gets_no_prefix(alice):
    txns(alice, 1)
    assert index.pending(alice, "mxbai-embed-large", DIGEST, 10)["items"][0]["text"] == "Shop0 x"


def test_pending_stops_at_the_limit_and_counts_what_remains(alice):
    txns(alice, 5)
    batch = index.pending(alice, MODEL, DIGEST, 2)
    assert len(batch["items"]) == 2 and batch["remaining"] == 3


def test_pending_never_shows_another_users_rows(alice, bob):
    txns(bob, 2)
    assert index.pending(alice, MODEL, DIGEST, 10) == {"items": [], "remaining": 0}


def test_stored_rows_are_no_longer_pending_and_count_as_indexed(alice):
    txns(alice, 3)
    assert index_all(alice) == {"stored": 3, "stale": 0, "rejected": 0}

    assert index.pending(alice, MODEL, DIGEST, 10) == {"items": [], "remaining": 0}
    assert index.status(alice, MODEL, DIGEST)["indexed"] == 3


@pytest.mark.parametrize(
    "model, digest", [("another-model", DIGEST), (MODEL, "sha256:bbbb")], ids=["model", "digest"]
)
def test_another_model_or_digest_makes_every_row_pending_again(alice, model, digest):
    txns(alice, 2)
    index_all(alice)
    assert len(index.pending(alice, model, digest, 10)["items"]) == 2


def test_a_new_text_version_makes_every_row_pending_again(alice, monkeypatch):
    txns(alice, 2)
    index_all(alice)
    monkeypatch.setattr(index, "TEXT_VERSION", 2)
    assert len(index.pending(alice, MODEL, DIGEST, 10)["items"]) == 2


def test_a_changed_text_is_pending_again(alice):
    (txn,) = txns(alice, 1)
    index_all(alice)
    set_name(txn, "Brandnew")

    (item,) = index.pending(alice, MODEL, DIGEST, 10)["items"]
    assert item["text"].startswith("search_document: Brandnew")


def test_a_category_change_moves_the_timestamp_without_re_embedding(alice):
    (txn,) = txns(alice, 1)
    index_all(alice)
    before = bytes(RagDocument.objects.get(transaction=txn).payload_enc)
    txn.category = Category.objects.filter(user=alice, is_default=False).first()
    txn.save()

    assert index.pending(alice, MODEL, DIGEST, 10) == {"items": [], "remaining": 0}
    doc = RagDocument.objects.get(transaction=txn)
    assert doc.source_updated_at == txn.updated_at
    assert bytes(doc.payload_enc) == before
    assert index.status(alice, MODEL, DIGEST)["indexed"] == 1


# --- store_vectors ----------------------------------------------------------------


def test_store_keeps_a_unit_vector_and_the_servers_own_text(alice):
    (txn,) = txns(alice, 1)
    (item,) = index.pending(alice, MODEL, DIGEST, 10)["items"]

    index.store_vectors(alice, MODEL, DIGEST, [{**item, "vector": [3.0, 0.0, 4.0, 0.0]}])

    doc, vec, text = stored(txn)
    assert vec.tolist() == pytest.approx([0.6, 0.0, 0.8, 0.0], abs=1e-3)
    assert text == "Shop0 x"  # no prefix: the prefix is for the embedding model only
    assert (doc.user, doc.model, doc.model_digest, doc.dims) == (alice, MODEL, DIGEST, 4)
    assert doc.text_version == index.TEXT_VERSION
    assert doc.source_updated_at == txn.updated_at
    assert bytes(doc.text_hash) == UserCipher(alice).blind_index(text.encode(), "rag.text")
    assert b"Shop0" not in bytes(doc.payload_enc)


def test_another_users_transaction_stores_nothing(alice, bob):
    (theirs,) = txns(bob, 1)
    item = {"transaction": str(theirs.id), "version": theirs.updated_at.isoformat()}

    result = index.store_vectors(alice, MODEL, DIGEST, [{**item, "vector": vector()}])

    assert result == {"stored": 0, "stale": 0, "rejected": 1}
    assert not RagDocument.objects.exists()


def test_a_row_edited_after_pending_is_stale_and_comes_back(alice):
    (txn,) = txns(alice, 1)
    batch = index.pending(alice, MODEL, DIGEST, 10)
    set_name(txn, "Edited")

    assert index.store_vectors(alice, MODEL, DIGEST, embed(batch["items"]))["stale"] == 1
    assert not RagDocument.objects.exists()
    assert index.pending(alice, MODEL, DIGEST, 10)["items"][0]["text"].startswith(
        "search_document: Edited"
    )


@pytest.mark.parametrize(
    "bad", [[0.0, 0.0, 0.0, 0.0], [0.1, float("nan"), 0.2, 0.3], [0.1, float("inf"), 0.2, 0.3]]
)
def test_an_unusable_vector_is_rejected(alice, bad):
    txns(alice, 1)
    (item,) = index.pending(alice, MODEL, DIGEST, 10)["items"]
    result = index.store_vectors(alice, MODEL, DIGEST, [{**item, "vector": bad}])
    assert result == {"stored": 0, "stale": 0, "rejected": 1}


def test_a_vector_over_the_dimension_limit_is_rejected(alice, settings):
    settings.RAG_MAX_DIMS = 3
    txns(alice, 1)
    (item,) = index.pending(alice, MODEL, DIGEST, 10)["items"]
    assert (
        index.store_vectors(alice, MODEL, DIGEST, [{**item, "vector": vector(4)}])["rejected"] == 1
    )


def test_an_id_that_is_not_a_uuid_is_rejected(alice):
    item = {"transaction": "not-a-uuid", "version": "x", "vector": vector()}
    assert index.store_vectors(alice, MODEL, DIGEST, [item])["rejected"] == 1


def test_a_transaction_repeated_in_one_batch_is_stored_once(alice):
    txns(alice, 1)
    (item,) = embed(index.pending(alice, MODEL, DIGEST, 10)["items"])
    assert index.store_vectors(alice, MODEL, DIGEST, [item, item]) == {
        "stored": 1,
        "stale": 0,
        "rejected": 1,
    }


def test_vectors_of_two_sizes_in_one_batch_are_refused(alice):
    txns(alice, 2)
    first, second = index.pending(alice, MODEL, DIGEST, 10)["items"]
    with pytest.raises(RagError) as error:
        index.store_vectors(
            alice, MODEL, DIGEST, [{**first, "vector": vector(4)}, {**second, "vector": vector(5)}]
        )
    assert error.value.code == "dimension_mismatch"
    assert not RagDocument.objects.exists()


def test_a_size_other_than_the_stored_one_is_refused_for_the_same_model(alice):
    txns(alice, 2)
    first, second = index.pending(alice, MODEL, DIGEST, 10)["items"]
    index.store_vectors(alice, MODEL, DIGEST, [{**first, "vector": vector(4)}])

    with pytest.raises(RagError) as error:
        index.store_vectors(alice, MODEL, DIGEST, [{**second, "vector": vector(5)}])
    assert error.value.code == "dimension_mismatch"
    # Another digest is another model version, which may have another size.
    assert (
        index.store_vectors(alice, MODEL, "sha256:bbbb", [{**second, "vector": vector(5)}])[
            "stored"
        ]
        == 1
    )


def test_storing_again_replaces_the_document_in_place(alice):
    (txn,) = txns(alice, 1)
    index_all(alice)
    first_id = RagDocument.objects.get(transaction=txn).id
    set_name(txn, "Renamed")

    (item,) = index.pending(alice, MODEL, DIGEST, 10)["items"]
    index.store_vectors(alice, MODEL, DIGEST, [{**item, "vector": [0.0, 1.0, 0.0, 0.0]}])

    doc, vec, text = stored(txn)
    assert RagDocument.objects.count() == 1 and doc.id == first_id
    assert text.startswith("Renamed") and vec.tolist() == [0.0, 1.0, 0.0, 0.0]


def test_the_index_log_line_carries_counts_and_never_text(alice, caplog):
    txns(alice, 2)
    with caplog.at_level(logging.INFO, logger="ai.rag.index"):
        index_all(alice)
    assert "stored=2 stale=0 rejected=0" in caplog.text
    assert "Shop" not in caplog.text and "SHOP" not in caplog.text


def test_a_whole_history_indexes_batch_by_batch_until_nothing_remains(alice):
    txns(alice, 7)
    rounds = 0
    while True:
        batch = index.pending(alice, MODEL, DIGEST, 3)
        if not batch["items"]:
            break
        index.store_vectors(alice, MODEL, DIGEST, embed(batch["items"]))
        rounds += 1
    assert rounds == 3 and batch["remaining"] == 0
    assert RagDocument.objects.filter(user=alice).count() == 7


# --- status and clear -------------------------------------------------------------


def test_status_reports_the_switch_the_counts_and_the_profile(alice, settings):
    txns(alice, 3)
    index.store_vectors(
        alice, MODEL, DIGEST, embed(index.pending(alice, MODEL, DIGEST, 1)["items"])
    )

    assert index.status(alice, MODEL, DIGEST) == {
        "enabled": True,
        "indexed": 1,
        "total": 3,
        "profile": {
            "doc_prefix": "search_document: ",
            "query_prefix": "search_query: ",
            "tuned": False,
        },
    }
    settings.RAG_ENABLED = False
    assert index.status(alice, MODEL, DIGEST)["enabled"] is False


def test_clear_deletes_only_the_users_own_index(alice, bob):
    txns(alice, 2)
    txns(bob, 1)
    index_all(alice)
    index_all(bob)

    assert index.clear(alice) == 2
    assert list(RagDocument.objects.values_list("user", flat=True)) == [bob.id]

import pytest
from django.db import IntegrityError, models, transaction
from django.test import Client

from accounts.models import User
from ai.models import RagDocument
from ai.rag import codec
from ai.rag.profiles import TEXT_VERSION
from transactions.tests import make_txn, make_user
from vault.services import UserCipher

pytestmark = pytest.mark.django_db


def make_doc(txn, **overrides):
    cipher = UserCipher(txn.user)
    values = dict(
        user=txn.user,
        transaction=txn,
        model="nomic-embed-text:latest",
        model_digest="sha256:0123456789abcdef",
        dims=3,
        text_version=TEXT_VERSION,
        payload_enc=cipher.encrypt(codec.pack([0.6, 0.0, 0.8], "Tastybites Cafe"), "rag.doc"),
        text_hash=cipher.blind_index(b"Tastybites Cafe", "rag.text"),
        source_updated_at=txn.updated_at,
    )
    values.update(overrides)
    return RagDocument.objects.create(**values)


@pytest.fixture
def alice():
    return make_user("alice@example.com")


def test_a_document_round_trips_through_the_database(alice):
    doc = make_doc(make_txn(alice))
    stored = RagDocument.objects.get(pk=doc.pk)

    payload = UserCipher(alice).decrypt(stored.payload_enc, "rag.doc")
    vector, text = codec.unpack(payload)
    assert text == "Tastybites Cafe" and vector.tolist() == pytest.approx([0.6, 0.0, 0.8], abs=1e-3)
    assert bytes(stored.text_hash) == UserCipher(alice).blind_index(b"Tastybites Cafe", "rag.text")


def test_the_plaintext_text_is_not_in_the_stored_row(alice):
    doc = make_doc(make_txn(alice))
    assert b"Tastybites" not in bytes(RagDocument.objects.get(pk=doc.pk).payload_enc)


def test_a_transaction_has_at_most_one_document(alice):
    txn = make_txn(alice)
    make_doc(txn)
    with pytest.raises(IntegrityError), transaction.atomic():
        make_doc(txn, model="another-model")


def test_deleting_the_transaction_deletes_its_document(alice):
    txn = make_txn(alice)
    make_doc(txn)
    txn.delete()
    assert not RagDocument.objects.exists()


def test_a_users_documents_go_with_the_user():
    # Asserted on the field: a user can't be deleted end to end yet, because Transaction.category
    # is PROTECT (account deletion is a later roadmap item).
    assert RagDocument._meta.get_field("user").remote_field.on_delete is models.CASCADE
    assert RagDocument._meta.get_field("transaction").remote_field.on_delete is models.CASCADE


@pytest.mark.parametrize("dims", [0, 4097])
def test_the_database_rejects_impossible_dimensions(alice, dims):
    with pytest.raises(IntegrityError), transaction.atomic():
        make_doc(make_txn(alice), dims=dims)


# --- admin --------------------------------------------------------------------


@pytest.fixture
def admin_client():
    admin = User.objects.create_superuser(email="admin@example.com", password="x-Str0ng-pass!")
    client = Client()
    client.force_login(admin)
    return client


def test_the_admin_lists_and_shows_documents_without_plaintext(alice, admin_client):
    doc = make_doc(make_txn(alice))

    for url in ("/admin/ai/ragdocument/", f"/admin/ai/ragdocument/{doc.id}/change/"):
        response = admin_client.get(url)
        assert response.status_code == 200
        assert "Tastybites" not in response.content.decode()
    assert (
        bytes(doc.payload_enc)[:8].hex()
        in admin_client.get("/admin/ai/ragdocument/").content.decode()
    )


def test_the_admin_cannot_add_documents(admin_client):
    assert admin_client.get("/admin/ai/ragdocument/add/").status_code == 403

"""Deleting an account deletes everything it has."""

import logging

import pytest
from django.apps import apps
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken

from accounts.models import User
from accounts.test_delete_data import PASSWORD, fill
from ai.models import RagDocument
from datasources.services import create_source
from transactions.models import Transaction, TransferLink
from transactions.tests import make_txn, make_user
from vault.models import UserDataKey
from vault.services import UserCipher, create_user_key

pytestmark = pytest.mark.django_db

URL = "/api/accounts/delete-account/"
LOGIN = "/api/accounts/login/"
REFRESH = "/api/accounts/refresh/"


def row_counts() -> dict[str, int]:
    """Rows in every table Django knows, including the ones a later phase adds."""
    return {model._meta.label: model.objects.count() for model in apps.get_models()}


def fill_everything(user):
    """fill() from the delete-data tests, plus the rows it doesn't make: a second data source, a
    transfer link, an Ask document, and the JWT records a real sign-in and a refresh leave."""
    fill(user)
    cipher = UserCipher(user)
    river = create_source(user, cipher, "River Bank")
    debit = make_txn(user, txn_type="debit", description="Transfer out")
    credit = make_txn(user, txn_type="credit", description="Transfer in", data_source=river)
    TransferLink.create_between(user, debit, credit)
    RagDocument.objects.create(
        user=user,
        transaction=debit,
        model="nomic-embed-text:latest",
        model_digest="sha256:0123456789ab",
        dims=3,
        text_version=1,
        payload_enc=cipher.encrypt(b"payload", "rag.doc"),
        text_hash=cipher.blind_index(b"text", "rag.text"),
        source_updated_at=timezone.now(),
    )


def signed_in(user) -> APIClient:
    """A browser that signed in for real (cookies) and refreshed once, so the user has both an
    outstanding and a blacklisted token."""
    client = APIClient()
    assert client.post(LOGIN, {"email": user.email, "password": PASSWORD}, format="json").status_code == 200
    assert client.post(REFRESH).status_code == 200
    return client


def delete(client, password=PASSWORD):
    return client.post(URL, {"password": password}, format="json")


@pytest.fixture
def alice():
    return make_user("alice@example.com")


# --- what is deleted ----------------------------------------------------------------


def test_every_table_is_back_to_what_it_held_before_the_account():
    bob = make_user("bob@example.com")  # another user's rows must survive untouched
    fill_everything(bob)
    signed_in(bob)
    before = row_counts()

    alice = make_user("alice@example.com")
    fill_everything(alice)
    client = signed_in(alice)
    assert OutstandingToken.objects.filter(user=alice).exists()
    assert BlacklistedToken.objects.filter(token__user=alice).exists()
    assert RagDocument.objects.filter(user=alice).exists()

    assert delete(client).status_code == 204
    assert row_counts() == before


def test_the_user_and_its_key_are_gone(alice):
    user_id = alice.pk
    assert delete(signed_in(alice)).status_code == 204
    assert not User.objects.filter(pk=user_id).exists()
    assert not UserDataKey.objects.filter(user_id=user_id).exists()


def test_the_other_users_data_is_never_touched(alice):
    bob = make_user("bob@example.com")
    fill_everything(bob)
    bob_rows = Transaction.objects.filter(user=bob).count()
    delete(signed_in(alice))
    assert Transaction.objects.filter(user=bob).count() == bob_rows
    assert UserCipher(bob)  # bob's key still opens


def test_the_email_can_sign_up_again_as_a_new_account(alice):
    delete(signed_in(alice))
    body = {"email": "alice@example.com", "password": PASSWORD, "birth_date": "1990-06-15"}
    assert APIClient().post("/api/accounts/register/", body, format="json").status_code == 201


def test_the_log_line_says_nothing_about_who(alice, caplog):
    user_id = str(alice.pk)
    with caplog.at_level(logging.INFO, logger="accounts.services"):
        delete(signed_in(alice))
    assert "an account was deleted" in caplog.text
    assert user_id not in caplog.text and "alice" not in caplog.text


# --- the browser is signed out ------------------------------------------------------


def test_the_cookies_are_cleared(alice):
    response = delete(signed_in(alice))
    assert response.cookies["access"].value == ""
    assert response.cookies["refresh"].value == ""


def test_an_old_refresh_cookie_gets_401_not_a_500(alice):
    client = signed_in(alice)
    old_refresh = client.cookies["refresh"].value
    delete(client)
    client.cookies["refresh"] = old_refresh
    assert client.post(REFRESH).status_code == 401


def test_an_old_access_cookie_is_just_anonymous(alice):
    client = signed_in(alice)
    old_access = client.cookies["access"].value
    delete(client)
    client.cookies["access"] = old_access
    assert client.get("/api/categories/").status_code == 401


# --- who may call it ------------------------------------------------------------------


def test_anonymous_requests_are_refused():
    assert APIClient().post(URL, {"password": PASSWORD}, format="json").status_code == 401


def test_get_is_not_allowed(alice):
    assert signed_in(alice).get(URL).status_code == 405


@pytest.mark.parametrize("body", [{}, {"password": ""}, {"password": "wrong-password-123"}])
def test_without_the_right_password_nothing_is_deleted(alice, body):
    fill(alice)
    response = signed_in(alice).post(URL, body, format="json")
    assert response.status_code == 400
    assert User.objects.filter(pk=alice.pk).exists()
    assert Transaction.objects.filter(user=alice).count() == 2


def test_the_password_is_never_echoed_back(alice):
    response = delete(signed_in(alice), "wrong-password-123")
    assert "wrong-password-123" not in str(response.data)


def test_an_account_without_a_date_of_birth_can_still_leave():
    user = User.objects.create_user(email="old@example.com", password=PASSWORD)
    create_user_key(user, PASSWORD)  # made before dates of birth were asked for
    client = APIClient()
    client.force_authenticate(user)
    assert delete(client).status_code == 204
    assert not User.objects.filter(email="old@example.com").exists()


def test_it_is_throttled_with_delete_data_after_five_attempts(alice):
    client = signed_in(alice)
    for _ in range(5):
        assert delete(client, "wrong-password-123").status_code == 400
    assert delete(client, "wrong-password-123").status_code == 429
    # Once throttled even the right password is refused, so it cannot be brute-forced here.
    assert delete(client).status_code == 429
    assert User.objects.filter(pk=alice.pk).exists()

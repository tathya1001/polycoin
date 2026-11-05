"""Phase 12.1 through the API: the password (or the recovery key) is the only way to the data.

Every test signs in for real, with cookies, and nothing is unlocked outside the requests: what a
request can read, it opened itself from the browser's vault session."""

import base64
import os

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.core.cache import cache
from rest_framework.test import APIClient

from accounts.models import User
from transactions.tests import make_txn, make_user
from vault import services
from vault.models import UserDataKey, VaultSession
from vault.services import forget_unlocked_keys, unlock_with_recovery_key

pytestmark = pytest.mark.django_db

PASSWORD = "x-Str0ng-pass!"  # make_user's
NEW_PASSWORD = "A-brand-new-Passw0rd"
LOGIN = "/api/accounts/login/"
REFRESH = "/api/accounts/refresh/"
LOGOUT = "/api/accounts/logout/"
CHANGE = "/api/accounts/change-password/"
RECOVER = "/api/accounts/recover/"
RECOVERY_KEY = "/api/accounts/recovery-key/"
TRANSACTIONS = "/api/transactions/"


def with_data(email="alice@example.com"):
    """A user with one transaction, and nothing unlocked afterwards."""
    user = make_user(email)
    make_txn(user, name="Tastybites")
    forget_unlocked_keys()
    return user


def login(client, email="alice@example.com", password=PASSWORD):
    return client.post(LOGIN, {"email": email, "password": password}, format="json")


def signed_in(email="alice@example.com", password=PASSWORD) -> APIClient:
    client = APIClient()
    assert login(client, email, password).status_code == 200
    return client


def names(client) -> list[str] | int:
    """The transaction names this browser can read, or the status code if it can't."""
    response = client.get(TRANSACTIONS)
    if response.status_code != 200:
        return response.status_code
    return [row["name"] for row in response.data["results"]]


def recovery_key_of(email="new@example.com") -> str:
    body = {"email": email, "password": PASSWORD, "birth_date": "1990-06-15"}
    response = APIClient().post("/api/accounts/register/", body, format="json")
    assert response.status_code == 201
    return response.data["recovery_key"]


# --- signing in opens the data; nothing else does ------------------------------------------------


def test_signing_in_opens_the_data():
    with_data()
    assert names(signed_in()) == ["Tastybites"]


def test_the_vault_cookie_is_httponly_and_api_only():
    with_data()
    cookie = login(APIClient()).cookies["vault"]
    assert cookie["httponly"] and cookie["path"] == "/api/"


def test_a_valid_access_token_without_the_vault_cookie_reads_nothing():
    with_data()
    client = signed_in()
    del client.cookies["vault"]
    assert names(client) == 401


def test_a_tampered_vault_cookie_reads_nothing():
    with_data()
    client = signed_in()
    session_id, _ = client.cookies["vault"].value.split(".")
    client.cookies["vault"] = f"{session_id}.{base64.urlsafe_b64encode(os.urandom(32)).decode()}"
    assert names(client) == 401


def test_another_users_vault_cookie_reads_nothing():
    with_data("alice@example.com")
    with_data("bob@example.com")
    alice, bob = signed_in("alice@example.com"), signed_in("bob@example.com")
    alice.cookies["vault"] = bob.cookies["vault"].value
    assert names(alice) == 401


def test_logging_out_locks_the_data_even_for_a_copied_cookie_jar():
    with_data()
    client = signed_in()
    stolen = {name: morsel.value for name, morsel in client.cookies.items()}
    assert client.post(LOGOUT).status_code == 204
    assert not VaultSession.objects.exists()

    thief = APIClient()
    for name, value in stolen.items():
        thief.cookies[name] = value
    assert names(thief) == 401  # the access token is still valid for minutes; the key is gone


def test_signing_in_again_replaces_this_browsers_session():
    user = with_data()
    client = signed_in()
    login(client)
    assert VaultSession.objects.filter(user=user).count() == 1
    assert names(client) == ["Tastybites"]


def test_two_browsers_have_two_sessions():
    user = with_data()
    first, second = signed_in(), signed_in()
    assert VaultSession.objects.filter(user=user).count() == 2
    assert names(first) == names(second) == ["Tastybites"]


# --- refreshing ------------------------------------------------------------------------------------


def test_a_refresh_renews_the_vault_cookie():
    with_data()
    client = signed_in()
    response = client.post(REFRESH)
    assert response.status_code == 200
    assert response.cookies["vault"].value == client.cookies["vault"].value
    assert names(client) == ["Tastybites"]


def test_a_refresh_without_the_vault_session_signs_the_browser_out():
    with_data()
    client = signed_in()
    VaultSession.objects.all().delete()
    response = client.post(REFRESH)
    assert response.status_code == 401
    assert response.cookies["access"].value == "" and response.cookies["vault"].value == ""


# --- accounts from before Phase 12.1 (D8, D9) ------------------------------------------------------


def make_legacy(settings):
    """alice as Phase 12 left her: her key locked with the master key only."""
    user = with_data()
    dek = services.unlock_with_password(user, PASSWORD).dek
    forget_unlocked_keys()
    master = os.urandom(32)
    settings.FIELD_ENCRYPTION_KEYS = f"v1:{base64.b64encode(master).decode()}"
    nonce = os.urandom(12)
    wrapped = nonce + AESGCM(master).encrypt(nonce, dek, f"dek:{user.id}".encode())
    UserDataKey.objects.filter(user=user).delete()
    UserDataKey.objects.create(user=user, wrapped_dek=wrapped, kek_version="v1")
    return user


def test_an_old_account_switches_over_at_login_and_gets_its_recovery_key_once(settings):
    user = make_legacy(settings)
    client = APIClient()
    first = login(client)
    assert first.status_code == 200
    recovery_key = first.data["recovery_key"]
    assert UserDataKey.objects.get(user=user).wrapped_dek is None
    assert names(client) == ["Tastybites"]

    settings.FIELD_ENCRYPTION_KEYS = ""  # the master key is destroyed
    second = signed_in()
    assert "recovery_key" not in login(APIClient()).data
    assert names(second) == ["Tastybites"]
    unlock_with_recovery_key(user, recovery_key)  # and the key shown once really works


def test_an_old_account_without_the_master_key_cannot_sign_in_and_is_not_changed(settings):
    user = make_legacy(settings)
    settings.FIELD_ENCRYPTION_KEYS = ""
    response = login(APIClient())
    assert response.status_code == 503
    assert response.data["code"] == "key_unavailable"
    assert "vault" not in response.cookies and "access" not in response.cookies
    assert UserDataKey.objects.get(user=user).wrapped_dek is not None


def test_a_password_set_outside_the_app_does_not_open_the_data():
    """D11: e.g. manage.py changepassword, which doesn't know about the lock."""
    user = with_data()
    user.set_password(NEW_PASSWORD)
    user.save()
    response = login(APIClient(), password=NEW_PASSWORD)
    assert response.status_code == 409
    assert response.data["code"] == "key_locked"
    assert "vault" not in response.cookies


# --- changing the password (D12) -------------------------------------------------------------------


def change(client, current=PASSWORD, new=NEW_PASSWORD):
    body = {"current_password": current, "new_password": new}
    return client.post(CHANGE, body, format="json")


def test_changing_the_password_moves_the_lock():
    user = with_data()
    recovery_key = services.replace_recovery_key(user, services.unlock_with_password(user, PASSWORD).dek)
    forget_unlocked_keys()
    here, elsewhere = signed_in(), signed_in()

    assert change(here).status_code == 204

    assert names(here) == ["Tastybites"]  # this browser stays signed in
    assert names(elsewhere) == 401  # every other one is locked out
    assert login(APIClient()).status_code == 401  # the old password is gone
    assert names(signed_in(password=NEW_PASSWORD)) == ["Tastybites"]
    unlock_with_recovery_key(user, recovery_key)  # the recovery key is unchanged


@pytest.mark.parametrize(
    "current, new, field",
    [
        ("wrong-password-1", NEW_PASSWORD, "current_password"),
        (PASSWORD, PASSWORD, "new_password"),
        (PASSWORD, "12345678", "new_password"),
    ],
)
def test_a_refused_change_changes_nothing(current, new, field):
    with_data()
    client = signed_in()
    response = change(client, current, new)
    assert response.status_code == 400 and field in response.data
    assert login(APIClient()).status_code == 200


def test_changing_the_password_needs_a_signed_in_browser():
    assert change(APIClient()).status_code == 401


# --- forgot password: the recovery key (D13) -------------------------------------------------------


def recover(email, key, new=NEW_PASSWORD):
    body = {"email": email, "recovery_key": key, "new_password": new}
    return APIClient().post(RECOVER, body, format="json")


def test_the_recovery_key_sets_a_new_password_and_closes_every_session():
    key = recovery_key_of()
    user = User.objects.get(email="new@example.com")
    browser = signed_in("new@example.com")
    old_refresh = browser.cookies["refresh"].value

    response = recover("new@example.com", key)

    assert response.status_code == 200
    new_key = response.data["recovery_key"]
    assert new_key != key
    assert not VaultSession.objects.filter(user=user).exists()
    assert names(browser) == 401
    browser.cookies["refresh"] = old_refresh
    assert browser.post(REFRESH).status_code == 401  # revoked
    cache.clear()  # sign-up, log-in and recovery share one 5-a-minute limit per address
    assert login(APIClient(), "new@example.com").status_code == 401  # the old password is gone
    assert login(APIClient(), "new@example.com", NEW_PASSWORD).status_code == 200
    assert recover("new@example.com", key).status_code == 400  # the old key is spent
    assert recover("new@example.com", new_key, "Another-new-Passw0rd").status_code == 200


def test_the_data_survives_a_recovery():
    user = with_data()
    key = services.replace_recovery_key(user, services.unlock_with_password(user, PASSWORD).dek)
    forget_unlocked_keys()
    assert recover("alice@example.com", key).status_code == 200
    assert names(signed_in(password=NEW_PASSWORD)) == ["Tastybites"]


@pytest.mark.parametrize(
    "email, key",
    [
        ("new@example.com", "AAAA-AAAA-AAAA-AAAA-AAAA-AAAA-AAAA-AAAA"),  # wrong key
        ("nobody@example.com", None),  # unknown email, right-looking key
        ("not an email", None),
        ("new@example.com", "garbage"),
    ],
)
def test_every_failure_gets_the_same_answer(email, key):
    real_key = recovery_key_of()
    response = recover(email, key or real_key)
    assert response.status_code == 400
    assert response.data == {"code": "recovery_failed", "detail": "That email and recovery key don't match."}
    assert login(APIClient(), "new@example.com").status_code == 200  # nothing changed


def test_a_weak_new_password_is_refused_and_nothing_changes():
    key = recovery_key_of()
    response = recover("new@example.com", key, "12345678")
    assert response.status_code == 400 and "new_password" in response.data
    assert login(APIClient(), "new@example.com").status_code == 200
    assert recover("new@example.com", key).status_code == 200  # the key still works


def test_recovery_is_throttled():
    key = recovery_key_of()
    cache.clear()
    for _ in range(5):
        assert recover("new@example.com", "AAAA-AAAA-AAAA-AAAA-AAAA-AAAA-AAAA-AAAA").status_code == 400
    assert recover("new@example.com", key).status_code == 429


# --- a new recovery key from Settings (D14) --------------------------------------------------------


def test_a_new_recovery_key_needs_the_password_and_replaces_the_old_one():
    old_key = recovery_key_of()
    client = signed_in("new@example.com")
    assert client.post(RECOVERY_KEY, {"password": "wrong-password-1"}, format="json").status_code == 400

    response = client.post(RECOVERY_KEY, {"password": PASSWORD}, format="json")
    assert response.status_code == 200
    new_key = response.data["recovery_key"]
    assert recover("new@example.com", old_key).status_code == 400
    assert recover("new@example.com", new_key).status_code == 200

"""Phase 12.2, D3 and D4: longer passwords, and failed sign-ins counted per account."""

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from transactions.tests import make_user

pytestmark = pytest.mark.django_db

LOGIN = "/api/accounts/login/"
RECOVER = "/api/accounts/recover/"
PASSWORD = "x-Str0ng-pass!"


def login(password, email="alice@example.com"):
    return APIClient().post(LOGIN, {"email": email, "password": password}, format="json")


@pytest.fixture
def alice():
    return make_user("alice@example.com")


# --- D3: twelve characters -------------------------------------------------------------------------


@pytest.mark.parametrize("password, ok", [("Elevenchar1", False), ("Twelvechars1", True)])
def test_a_password_needs_twelve_characters(password, ok):
    body = {"email": "new@example.com", "password": password, "birth_date": "1990-06-15"}
    response = APIClient().post("/api/accounts/register/", body, format="json")
    assert (response.status_code == 201) is ok
    if not ok:
        assert "12 characters" in str(response.data["password"])


# --- D4: failed sign-ins per account ---------------------------------------------------------------


@pytest.fixture
def many_addresses(settings):
    """As if each attempt came from another address: the per-address limit out of the way. The
    rates dict is shared, so it is put back by hand (the settings fixture wouldn't)."""
    rates = settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]
    original = rates["auth"]
    rates["auth"] = "1000/min"
    yield
    rates["auth"] = original


def fail_logins(times):
    for _ in range(times):
        assert login("wrong-password-123").status_code == 401


def test_ten_failures_lock_the_account_even_from_many_addresses(alice, many_addresses):
    fail_logins(10)
    response = login(PASSWORD)  # even the right password, until the hour is up
    assert response.status_code == 429
    assert response.data["code"] == "account_locked"
    assert "recovery key" in response.data["detail"]


def test_nine_failures_still_let_the_right_password_in(alice, many_addresses):
    fail_logins(9)
    assert login(PASSWORD).status_code == 200


def test_successful_logins_do_not_count(alice, many_addresses):
    for _ in range(12):
        assert login(PASSWORD).status_code == 200


def test_the_count_is_per_account(alice, many_addresses):
    make_user("bob@example.com")
    fail_logins(10)
    response = APIClient().post(
        LOGIN, {"email": "bob@example.com", "password": PASSWORD}, format="json"
    )
    assert response.status_code == 200


def test_failed_recoveries_count_too(alice, many_addresses):
    body = {
        "email": "alice@example.com",
        "recovery_key": "AAAA-AAAA-AAAA-AAAA-AAAA-AAAA-AAAA-AAAA",
        "new_password": "A-brand-new-Passw0rd",
    }
    for _ in range(10):
        assert APIClient().post(RECOVER, body, format="json").status_code == 400
    assert login(PASSWORD).status_code == 429


def test_the_cache_never_holds_the_email(alice, many_addresses):
    fail_logins(1)
    keys = [str(key) for key in getattr(cache, "_cache", {})]
    assert keys and not any("alice" in key for key in keys)

"""Phase 12.2, D1 and D2: another site can't sign a visitor in, sign them up, or recover an account.

The audit's proof of the hole: a plain HTML form on another site, posting the attacker's email
and password to /api/accounts/login/, logged the visitor in and set the session cookies.
"""

import pytest
from rest_framework.test import APIClient

from transactions.tests import make_user

pytestmark = pytest.mark.django_db

PASSWORD = "x-Str0ng-pass!"
OPEN_ENDPOINTS = {
    "/api/accounts/login/": {"email": "alice@example.com", "password": PASSWORD},
    "/api/accounts/register/": {
        "email": "new@example.com",
        "password": PASSWORD,
        "birth_date": "1990-06-15",
    },
    "/api/accounts/recover/": {
        "email": "alice@example.com",
        "recovery_key": "AAAA-AAAA-AAAA-AAAA-AAAA-AAAA-AAAA-AAAA",
        "new_password": "A-brand-new-Passw0rd",
    },
}


@pytest.fixture(autouse=True)
def alice():
    return make_user("alice@example.com")


def browser() -> APIClient:
    """A client that checks CSRF the way a real browser request is checked."""
    return APIClient(enforce_csrf_checks=True)


def token(client) -> str:
    client.get("/api/accounts/csrf/")
    return client.cookies["csrftoken"].value


@pytest.mark.parametrize("url", OPEN_ENDPOINTS)
def test_without_the_csrf_token_it_is_refused(url):
    response = browser().post(url, OPEN_ENDPOINTS[url], format="json")
    assert response.status_code == 403
    assert "access" not in response.cookies and "vault" not in response.cookies


@pytest.mark.parametrize("url", OPEN_ENDPOINTS)
def test_another_sites_origin_is_refused_even_with_a_token(url):
    client = browser()
    response = client.post(
        url,
        OPEN_ENDPOINTS[url],
        format="json",
        HTTP_X_CSRFTOKEN=token(client),
        HTTP_ORIGIN="https://evil.example",
    )
    assert response.status_code == 403


def test_the_audits_form_post_no_longer_logs_anyone_in():
    response = browser().post(
        "/api/accounts/login/",
        "email=alice%40example.com&password=x-Str0ng-pass%21",
        content_type="application/x-www-form-urlencoded",
        HTTP_ORIGIN="https://evil.example",
    )
    assert response.status_code == 403
    assert "access" not in response.cookies and "vault" not in response.cookies


def test_a_form_body_is_not_read_even_with_a_token():
    """D2: the API reads JSON only, so a cross-site form body can't be parsed."""
    client = browser()
    response = client.post(
        "/api/accounts/login/",
        "email=alice%40example.com&password=x-Str0ng-pass%21",
        content_type="application/x-www-form-urlencoded",
        HTTP_X_CSRFTOKEN=token(client),
    )
    assert response.status_code == 415


def test_the_app_with_its_token_still_logs_in():
    client = browser()
    response = client.post(
        "/api/accounts/login/",
        OPEN_ENDPOINTS["/api/accounts/login/"],
        format="json",
        HTTP_X_CSRFTOKEN=token(client),
    )
    assert response.status_code == 200

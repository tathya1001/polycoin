import pytest
from rest_framework.test import APIClient

from .models import User

EMAIL = "me@example.com"
PASSWORD = "S3cure-pass-998"

REGISTER = "/api/accounts/register/"
LOGIN = "/api/accounts/login/"
REFRESH = "/api/accounts/refresh/"
LOGOUT = "/api/accounts/logout/"
ME = "/api/accounts/me/"
CSRF = "/api/accounts/csrf/"


@pytest.fixture
def client():
    # enforce_csrf_checks=True so tests exercise the real CSRF behaviour
    return APIClient(enforce_csrf_checks=True)


@pytest.fixture
def user(db):
    return User.objects.create_user(EMAIL, PASSWORD)


def login(client, email=EMAIL, password=PASSWORD):
    return client.post(LOGIN, {"email": email, "password": password}, format="json")


def csrf_header(client):
    """Fetch the csrftoken cookie and return the header a browser would echo back."""
    client.get(CSRF)
    return {"HTTP_X_CSRFTOKEN": client.cookies["csrftoken"].value}


# --- register ---------------------------------------------------------------


def test_register_creates_user_without_leaking_secrets(client, db):
    r = client.post(REGISTER, {"email": "new@example.com", "password": PASSWORD}, format="json")
    assert r.status_code == 201
    assert set(r.json()) == {"id", "email"}
    assert User.objects.get(email="new@example.com").password.startswith("argon2$argon2id$")


def test_register_rejects_duplicate_email_case_insensitively(client, user):
    r = client.post(REGISTER, {"email": EMAIL.upper(), "password": PASSWORD}, format="json")
    assert r.status_code == 400


def test_register_rejects_weak_password(client, db):
    r = client.post(REGISTER, {"email": "weak@example.com", "password": "12345678"}, format="json")
    assert r.status_code == 400
    assert not User.objects.filter(email="weak@example.com").exists()


# --- login ------------------------------------------------------------------


def test_login_sets_httponly_cookies_and_no_tokens_in_body(client, user):
    r = login(client)
    assert r.status_code == 200
    assert "access" not in r.json() and "refresh" not in r.json()
    assert r.cookies["access"]["httponly"]
    assert r.cookies["refresh"]["httponly"]
    assert r.cookies["refresh"]["path"] == "/api/accounts/"


def test_login_wrong_password_gives_401_and_no_cookies(client, user):
    r = login(client, password="wrong-password-123")
    assert r.status_code == 401
    assert "access" not in r.cookies and "refresh" not in r.cookies


def test_login_errors_do_not_reveal_whether_email_exists(client, user):
    wrong_pw = login(client, password="wrong-password-123")
    unknown = login(client, email="nobody@example.com")
    assert wrong_pw.status_code == unknown.status_code == 401
    assert wrong_pw.json() == unknown.json()


def test_login_is_throttled_after_five_attempts(client, user):
    for _ in range(5):
        assert login(client, password="wrong-password-123").status_code == 401
    assert login(client, password="wrong-password-123").status_code == 429


# --- me / cookie auth -------------------------------------------------------


def test_me_requires_auth(client, db):
    assert client.get(ME).status_code == 401


def test_me_returns_current_user(client, user):
    assert login(client).status_code == 200
    r = client.get(ME)
    assert r.status_code == 200
    assert r.json()["email"] == EMAIL
    assert str(user.id) == r.json()["id"]


def test_me_does_not_leak_password(client, user):
    login(client)
    assert "password" not in client.get(ME).json()


def test_me_rejects_garbage_cookie(client, db):
    client.cookies["access"] = "not-a-jwt"
    assert client.get(ME).status_code == 401


def test_stale_access_cookie_does_not_break_public_endpoints(client, db):
    """An expired/garbage access cookie must be treated as anonymous, not as an error."""
    client.cookies["access"] = "not-a-jwt"
    assert client.get("/api/health/").status_code == 200
    r = client.post(REGISTER, {"email": "stale@example.com", "password": PASSWORD}, format="json")
    assert r.status_code == 201


def test_access_cookie_outlives_the_token(client, user):
    r = login(client)
    assert int(r.cookies["access"]["max-age"]) == 7 * 24 * 3600


def test_cookie_auth_enforces_csrf_on_unsafe_methods(client, user):
    """With a valid access cookie, a POST lacking the CSRF header is blocked (403).
    With the header, auth passes and we reach the 405 'method not allowed' for /me."""
    login(client)
    assert client.post(ME).status_code == 403
    assert client.post(ME, **csrf_header(client)).status_code == 405


# --- refresh ----------------------------------------------------------------


def test_refresh_requires_csrf(client, user):
    login(client)
    assert client.post(REFRESH).status_code == 403


def test_refresh_without_cookie_gives_401(client, db):
    assert client.post(REFRESH, **csrf_header(client)).status_code == 401


def test_refresh_issues_new_cookies(client, user):
    login(client)
    old_refresh = client.cookies["refresh"].value
    r = client.post(REFRESH, **csrf_header(client))
    assert r.status_code == 200
    assert r.cookies["access"]["httponly"]
    assert r.cookies["refresh"].value != old_refresh  # rotation
    assert client.get(ME).status_code == 200


def test_reusing_a_rotated_refresh_token_is_rejected(client, user):
    login(client)
    old_refresh = client.cookies["refresh"].value
    headers = csrf_header(client)
    assert client.post(REFRESH, **headers).status_code == 200
    client.cookies["refresh"] = old_refresh  # attacker replays the stolen old token
    assert client.post(REFRESH, **headers).status_code == 401


# --- logout -----------------------------------------------------------------


def test_logout_requires_csrf(client, user):
    login(client)
    assert client.post(LOGOUT).status_code == 403


def test_logout_clears_cookies_and_revokes_refresh_token(client, user):
    login(client)
    stolen_refresh = client.cookies["refresh"].value
    headers = csrf_header(client)

    r = client.post(LOGOUT, **headers)
    assert r.status_code == 204
    assert r.cookies["access"].value == "" and r.cookies["refresh"].value == ""

    client.cookies["refresh"] = stolen_refresh  # replay after logout
    assert client.post(REFRESH, **headers).status_code == 401


def test_logout_succeeds_even_with_invalid_refresh_token(client, db):
    client.cookies["refresh"] = "garbage"
    assert client.post(LOGOUT, **csrf_header(client)).status_code == 204

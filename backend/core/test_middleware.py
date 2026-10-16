"""OriginSecretMiddleware and NoStoreApiMiddleware."""

import pytest
from django.test import Client

SECRET = "origin-secret-5d2f"  # stands in for the real ORIGIN_SECRET
CSRF = "/api/accounts/csrf/"  # an open endpoint that needs no login


# --- OriginSecretMiddleware ---------------------------------------------------


@pytest.mark.django_db
def test_origin_check_is_off_when_no_secret_is_configured(settings):
    settings.ORIGIN_SECRET = ""
    assert Client().get(CSRF).status_code == 200


@pytest.mark.django_db
def test_requests_without_the_secret_are_refused_when_one_is_configured(settings):
    settings.ORIGIN_SECRET = SECRET
    response = Client().get(CSRF)
    assert response.status_code == 403
    assert response.json() == {"detail": "Forbidden."}


@pytest.mark.django_db
def test_a_wrong_secret_is_refused(settings):
    settings.ORIGIN_SECRET = SECRET
    assert Client().get(CSRF, HTTP_X_ORIGIN_SECRET="not-it").status_code == 403


@pytest.mark.django_db
def test_the_right_secret_is_accepted(settings):
    settings.ORIGIN_SECRET = SECRET
    assert Client().get(CSRF, HTTP_X_ORIGIN_SECRET=SECRET).status_code == 200


@pytest.mark.django_db
@pytest.mark.parametrize("path", ["/api/ping/", "/api/health/"])
def test_probes_work_without_the_secret(settings, path):
    """Render's health check, the keep-alive and the deploy pipeline call these directly."""
    settings.ORIGIN_SECRET = SECRET
    assert Client().get(path).status_code == 200


@pytest.mark.django_db
def test_the_check_only_covers_the_api(settings):
    """The admin is not reached through Vercel, so it is not behind the origin secret."""
    settings.ORIGIN_SECRET = SECRET
    assert Client().get("/admin/login/").status_code == 200


@pytest.mark.django_db
def test_an_unauthenticated_post_is_refused_before_it_reaches_the_view(settings):
    settings.ORIGIN_SECRET = SECRET
    response = Client().post("/api/accounts/login/", {"email": "a@b.test", "password": "x"})
    assert response.status_code == 403


# --- NoStoreApiMiddleware -----------------------------------------------------


def test_api_responses_are_marked_uncacheable():
    cache_control = Client().get("/api/ping/")["Cache-Control"]
    assert "no-store" in cache_control
    assert "private" in cache_control


def test_the_middleware_leaves_non_api_responses_alone():
    assert "Cache-Control" not in Client().get("/not-an-api-path/")

import pytest
from django.test import Client
from django.urls import URLPattern, URLResolver, get_resolver
from rest_framework.permissions import AllowAny
from rest_framework.views import APIView

# Keep in sync with the comment in config/urls.py.
EXPECTED_OPEN_ENDPOINTS = {
    "api/health/",
    "api/accounts/csrf/",
    "api/accounts/register/",
    "api/accounts/login/",
    "api/accounts/refresh/",
    "api/accounts/logout/",
}


def _api_routes(patterns, prefix=""):
    """Yield (route, view_class) for every DRF view reachable from the URLconf."""
    for p in patterns:
        route = prefix + str(p.pattern)
        if isinstance(p, URLResolver):
            yield from _api_routes(p.url_patterns, route)
        elif isinstance(p, URLPattern):
            view_class = getattr(p.callback, "cls", None)  # set by as_view()/@api_view
            if view_class is not None and issubclass(view_class, APIView):
                yield route, view_class


def test_only_expected_endpoints_are_open():
    """Secure by default: a new view that forgets permissions fails closed, and
    anything that opts out (AllowAny) must be added to the allowlist above."""
    routes = list(_api_routes(get_resolver().url_patterns))
    assert routes, "no API routes found; the walker is broken"
    open_routes = {
        route
        for route, view in routes
        if any(
            isinstance(perm, type) and issubclass(perm, AllowAny)
            for perm in view.permission_classes
        )
    }
    assert open_routes == EXPECTED_OPEN_ENDPOINTS


@pytest.mark.django_db
def test_health_returns_ok():
    client = Client()
    response = client.get("/api/health/")
    assert response.status_code == 200
    assert response.json()["database"] == "ok"

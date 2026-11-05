"""The URL map that production serves."""

import importlib

import pytest
from django.urls import Resolver404, clear_url_caches, resolve

import config.urls


@pytest.fixture
def load_urls(settings):
    """Rebuild config.urls as one environment would see it, and put the normal map back after.

    This fixture's teardown runs before `settings` restores the real values, so it restores
    PRODUCTION itself before rebuilding the map."""
    original = settings.PRODUCTION

    def load(production: bool):
        settings.PRODUCTION = production
        importlib.reload(config.urls)
        clear_url_caches()

    yield load
    settings.PRODUCTION = original
    importlib.reload(config.urls)
    clear_url_caches()


def test_production_has_no_admin(load_urls):
    load_urls(production=True)
    with pytest.raises(Resolver404):
        resolve("/admin/")
    with pytest.raises(Resolver404):
        resolve("/admin/login/")


def test_production_still_serves_the_api(load_urls):
    load_urls(production=True)
    assert resolve("/api/ping/")
    assert resolve("/api/accounts/login/")


def test_local_development_keeps_the_admin(load_urls):
    load_urls(production=False)
    assert resolve("/admin/login/")

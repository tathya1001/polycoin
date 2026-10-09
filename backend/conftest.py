import pytest
from django.core.cache import cache


@pytest.fixture(autouse=True)
def clear_throttle_cache():
    """The 'auth' throttle (5/min) stores its counters in the cache, which would
    otherwise persist across tests and make later login-based tests hit 429."""
    cache.clear()

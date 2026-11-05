import pytest
from django.core.cache import cache

from vault.services import forget_unlocked_keys


@pytest.fixture(autouse=True)
def clear_throttle_cache():
    """The 'auth' throttle (5/min) stores its counters in the cache, which would
    otherwise persist across tests and make later login-based tests hit 429."""
    cache.clear()


@pytest.fixture(autouse=True)
def fast_vault(settings):
    """Each user's key is locked with Argon2id(password): about 0.1 s at production strength, and
    the tests make thousands of users. Weak settings are safe here because every lock stores the
    settings it was made with; vault/tests.py pins the production ones.

    Keys unlocked by one test (creating a user unlocks theirs) must not leak into the next."""
    settings.VAULT_KDF_TIME_COST = 1
    settings.VAULT_KDF_MEMORY_KIB = 8  # Argon2's minimum: 8 KiB per lane
    settings.VAULT_KDF_PARALLELISM = 1
    forget_unlocked_keys()
    yield
    forget_unlocked_keys()

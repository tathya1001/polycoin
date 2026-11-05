"""Failed sign-ins, counted per account (Phase 12.2, D4).

The "auth" throttle limits each address to 5 attempts a minute. That alone lets someone guess one
account's password from many addresses. So failures are also counted per account: 10 an hour,
counting failed logins and failed recoveries together. Only failures count, so a stranger can't use
up the limit by signing in correctly.

The cache key is a hash of the normalised email, so the cache table never holds an address.
"""

import hashlib

from django.core.cache import cache
from rest_framework import status
from rest_framework.response import Response

MAX_FAILURES = 10
WINDOW_SECONDS = 60 * 60


def _key(email) -> str | None:
    if not isinstance(email, str) or not email.strip():
        return None
    digest = hashlib.sha256(email.strip().lower().encode()).hexdigest()
    return f"failed-sign-ins:{digest}"


def account_is_locked(email) -> bool:
    key = _key(email)
    return key is not None and cache.get(key, 0) >= MAX_FAILURES


def record_failure(email) -> None:
    key = _key(email)
    if key is None:
        return
    cache.add(key, 0, WINDOW_SECONDS)  # starts the window; does nothing if one is running
    try:
        cache.incr(key)
    except ValueError:  # it expired between the two calls
        cache.set(key, 1, WINDOW_SECONDS)


def too_many_failures() -> Response:
    return Response(
        {
            "code": "account_locked",
            "detail": "Too many failed attempts for this account. Try again in an hour, "
            "or set a new password with your recovery key.",
        },
        status=status.HTTP_429_TOO_MANY_REQUESTS,
    )

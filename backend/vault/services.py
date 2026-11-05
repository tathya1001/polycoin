"""Per-user encryption keys. Phase 12.1: the password is the key.

Each user has one random data key (DEK). Every encrypted column of theirs is AES-256-GCM under it,
and it never changes, so nothing is ever re-encrypted. What protects it is how it is stored
(vault.models.UserDataKey): locked with a key derived from the user's password, and locked with
their recovery key. Neither of those is stored, so the database, even together with every
environment variable, can't open it.

While a user is signed in, one more copy is locked with a random secret that only their browser
holds (VaultSession + the "vault" cookie). Each request opens it into a per-request registry
(`request_scope`), and UserCipher reads the key from there, for that request only.

Why each piece is the way it is: dev-docs/phase-12.1-password-key-plan.md (decisions D1-D18).
"""

import base64
import binascii
import hashlib
import hmac
import os
import uuid
from contextlib import contextmanager
from contextvars import ContextVar

from argon2.low_level import Type, hash_secret_raw
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from django.conf import settings
from django.utils import timezone

from .models import UserDataKey, VaultSession

BLOB_VERSION = 1
NONCE_SIZE = 12  # 96 bits, the size GCM is designed for
KEY_SIZE = 32  # AES-256
SALT_SIZE = 16
RECOVERY_KEY_BYTES = 20  # 160 bits, written as 32 base32 characters
SESSION_SECRET_BYTES = 32


class VaultLocked(Exception):
    """The user's data key is not unlocked in this request: there is no signed-in session."""


class WrongSecret(Exception):
    """The password or recovery key does not open this user's data key."""


# --- locks ---------------------------------------------------------------------------------------
# A lock is AES-256-GCM: nonce(12) | ciphertext + tag. Its associated data names the user and the
# kind of lock, so a lock can't be copied onto another user's row or used as a different kind.


def _lock(key: bytes, dek: bytes, aad: bytes) -> bytes:
    nonce = os.urandom(NONCE_SIZE)
    return nonce + AESGCM(key).encrypt(nonce, dek, aad)


def _open(key: bytes, blob, aad: bytes) -> bytes:
    blob = bytes(blob)  # Postgres may hand back a memoryview
    return AESGCM(key).decrypt(blob[:NONCE_SIZE], blob[NONCE_SIZE:], aad)  # InvalidTag if wrong


def _aad(user_id, kind: str) -> bytes:
    return f"dek:{user_id}:{kind}".encode()


# --- the password key (D2) -----------------------------------------------------------------------


def _current_kdf() -> dict[str, int]:
    return {
        "t": settings.VAULT_KDF_TIME_COST,
        "m": settings.VAULT_KDF_MEMORY_KIB,
        "p": settings.VAULT_KDF_PARALLELISM,
    }


def _format_kdf(params: dict[str, int]) -> str:
    return "argon2id:" + ",".join(f"{name}={params[name]}" for name in ("t", "m", "p"))


def _parse_kdf(text: str) -> dict[str, int]:
    kind, _, rest = text.partition(":")
    if kind != "argon2id":
        raise ValueError(f"Unknown key derivation {kind!r}.")
    return {name: int(value) for name, value in (item.split("=") for item in rest.split(","))}


def _password_key(password: str, salt: bytes, params: dict[str, int]) -> bytes:
    return hash_secret_raw(
        secret=password.encode(),
        salt=salt,
        time_cost=params["t"],
        memory_cost=params["m"],  # KiB
        parallelism=params["p"],
        hash_len=KEY_SIZE,
        type=Type.ID,
    )


# --- the recovery key (D3) -----------------------------------------------------------------------


def _new_recovery_key() -> tuple[str, bytes]:
    """("ABCD-EFGH-...", its 20 bytes). Base32 has no 0, 1, 8 or 9."""
    raw = os.urandom(RECOVERY_KEY_BYTES)
    text = base64.b32encode(raw).decode()  # 32 characters, no padding for 20 bytes
    return "-".join(text[i : i + 4] for i in range(0, len(text), 4)), raw


def _recovery_bytes(text: str) -> bytes | None:
    """The bytes of a recovery key as the user typed it: any case, spaces and dashes ignored, and
    a 0 or 1 read as the O or I it must have been. None if it can't be one."""
    cleaned = "".join(str(text).split()).replace("-", "").upper().replace("0", "O").replace("1", "I")
    if len(cleaned) != 32:
        return None
    try:
        raw = base64.b32decode(cleaned)
    except (binascii.Error, ValueError):
        return None
    return raw if len(raw) == RECOVERY_KEY_BYTES else None


def _recovery_lock_key(raw: bytes) -> bytes:
    # HKDF, not Argon2: the recovery key is 160 random bits, so there is nothing to slow down.
    return HKDF(
        algorithm=hashes.SHA256(), length=KEY_SIZE, salt=None, info=b"moneyangle recovery key"
    ).derive(raw)


# --- the per-request registry (D5, D17) ----------------------------------------------------------

_unlocked: ContextVar[dict | None] = ContextVar("vault_unlocked", default=None)


@contextmanager
def request_scope():
    """Run one request with its own registry of unlocked keys, emptied when it ends.

    It starts as a copy of whatever was unlocked outside any request. Production never unlocks a
    key outside a request, so there that copy is always empty; tests do (D17)."""
    token = _unlocked.set(dict(_unlocked.get() or {}))
    try:
        yield
    finally:
        _unlocked.reset(token)


def _remember(user, dek: bytes) -> None:
    keys = _unlocked.get()
    if keys is None:  # outside any request: only tests and management commands get here
        keys = {}
        _unlocked.set(keys)
    keys[user.pk] = dek


def unlocked_key(user) -> bytes:
    dek = (_unlocked.get() or {}).get(user.pk)
    if dek is None:
        raise VaultLocked("This user's data key is not unlocked in this request.")
    return dek


def forget_unlocked_keys() -> None:
    """Empty the registry outside a request (tests use it between tests)."""
    _unlocked.set(None)


# --- creating and opening a user's key -----------------------------------------------------------


def _set_password_lock(record: UserDataKey, dek: bytes, password: str) -> None:
    params = _current_kdf()
    salt = os.urandom(SALT_SIZE)
    key = _password_key(password, salt, params)
    record.password_wrapped_dek = _lock(key, dek, _aad(record.user_id, "password"))
    record.password_salt = salt
    record.kdf_params = _format_kdf(params)


def _set_recovery_lock(record: UserDataKey, dek: bytes) -> str:
    text, raw = _new_recovery_key()
    record.recovery_wrapped_dek = _lock(_recovery_lock_key(raw), dek, _aad(record.user_id, "recovery"))
    return text


def create_user_key(user, password: str) -> str:
    """A new user's data key, locked with their password and a new recovery key. Returns the
    recovery key, to show them once. The key is unlocked for the rest of this request."""
    dek = os.urandom(KEY_SIZE)
    record = UserDataKey(user=user)
    _set_password_lock(record, dek, password)
    recovery_key = _set_recovery_lock(record, dek)
    record.save()
    _remember(user, dek)
    return recovery_key


def unlock_with_password(user, password: str) -> bytes:
    """Open the user's key with their password, for this request, and return it.
    Raises WrongSecret if the password doesn't open it (12.1, D11)."""
    record = UserDataKey.objects.get(user=user)
    params = _parse_kdf(record.kdf_params)
    key = _password_key(password, bytes(record.password_salt), params)
    try:
        dek = _open(key, record.password_wrapped_dek, _aad(user.pk, "password"))
    except InvalidTag:
        raise WrongSecret from None
    if params != _current_kdf():  # 12.1, D10: re-lock with the current settings
        _set_password_lock(record, dek, password)
        record.save(update_fields=["password_wrapped_dek", "password_salt", "kdf_params"])
    _remember(user, dek)
    return dek


def unlock_with_recovery_key(user, recovery_key: str) -> bytes:
    """Open the user's key with their recovery key, for this request. Raises WrongSecret."""
    record = UserDataKey.objects.filter(user=user).first()
    raw = _recovery_bytes(recovery_key)
    if record is None or record.recovery_wrapped_dek is None or raw is None:
        raise WrongSecret
    try:
        dek = _open(_recovery_lock_key(raw), record.recovery_wrapped_dek, _aad(user.pk, "recovery"))
    except InvalidTag:
        raise WrongSecret from None
    _remember(user, dek)
    return dek


def set_password_lock(user, dek: bytes, password: str) -> None:
    """After a password change or a recovery: lock the key with the new password. The old password
    stops opening it. The recovery key is left as it is (D12)."""
    record = UserDataKey.objects.get(user=user)
    _set_password_lock(record, dek, password)
    record.save(update_fields=["password_wrapped_dek", "password_salt", "kdf_params"])


def replace_recovery_key(user, dek: bytes) -> str:
    """A new recovery key. The old one stops opening the key. Returns the new one, to show once."""
    record = UserDataKey.objects.get(user=user)
    recovery_key = _set_recovery_lock(record, dek)
    record.save(update_fields=["recovery_wrapped_dek"])
    return recovery_key


# --- browser sessions (D4, D6, D7) ---------------------------------------------------------------


def _session_lifetime():
    return settings.SIMPLE_JWT["REFRESH_TOKEN_LIFETIME"]  # D7: as long as the login


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _parse_cookie(value) -> tuple[uuid.UUID, bytes] | None:
    if not value:
        return None
    session_id, _, secret_text = str(value).partition(".")
    try:
        parsed_id = uuid.UUID(session_id)
        secret = base64.urlsafe_b64decode(secret_text + "=" * (-len(secret_text) % 4))
    except (ValueError, binascii.Error):
        return None
    return (parsed_id, secret) if len(secret) == SESSION_SECRET_BYTES else None


def open_session(user, dek: bytes) -> str:
    """Lock `dek` to a new browser session. Returns the "vault" cookie's value, which holds the
    only copy of the session's secret."""
    now = timezone.now()
    VaultSession.objects.filter(expires_at__lte=now).delete()  # everyone's stale ones (12.2, D8)
    secret = os.urandom(SESSION_SECRET_BYTES)
    session = VaultSession(user=user, expires_at=now + _session_lifetime())
    session.wrapped_dek = _lock(secret, dek, _aad(user.pk, f"session:{session.pk}"))
    session.save()
    return f"{session.pk}.{_b64(secret)}"


def _open_session(user_id, cookie) -> tuple[VaultSession, bytes] | None:
    parsed = _parse_cookie(cookie)
    if parsed is None:
        return None
    session_id, secret = parsed
    session = VaultSession.objects.filter(
        pk=session_id, user_id=user_id, expires_at__gt=timezone.now()
    ).first()
    if session is None:
        return None
    try:
        dek = _open(secret, session.wrapped_dek, _aad(user_id, f"session:{session.pk}"))
    except InvalidTag:
        return None
    return session, dek


def unlock_session(user, cookie) -> bool:
    """Open this browser's session into the current request. False if it has no usable one."""
    opened = _open_session(user.pk, cookie)
    if opened is None:
        return False
    _remember(user, opened[1])
    return True


def renew_session(user_id, cookie) -> bool:
    """On a token refresh: check the browser's session still opens, and extend it (D7)."""
    opened = _open_session(user_id, cookie)
    if opened is None:
        return False
    session = opened[0]
    session.expires_at = timezone.now() + _session_lifetime()
    session.save(update_fields=["expires_at"])
    return True


def close_session(cookie) -> None:
    """Log-out: delete this browser's session, and with it this copy of the key."""
    parsed = _parse_cookie(cookie)
    if parsed is not None:
        VaultSession.objects.filter(pk=parsed[0]).delete()


def close_other_sessions(user, keep_cookie) -> None:
    """Every session of the user except this browser's (after a password change, D12)."""
    others = VaultSession.objects.filter(user=user)
    parsed = _parse_cookie(keep_cookie)
    if parsed is not None:
        others = others.exclude(pk=parsed[0])
    others.delete()


def close_all_sessions(user) -> None:
    VaultSession.objects.filter(user=user).delete()


# --- encrypting the user's data ------------------------------------------------------------------


def _data_aad(user, context: str) -> bytes:
    # Binds ciphertext to its owner AND the field it belongs to.
    return f"{user.id}:{context}".encode()


class UserCipher:
    """One user's data key, for their fields in this request. Raises VaultLocked if the key isn't
    unlocked here, so code can never read data without the user's session (D5)."""

    def __init__(self, user):
        self.user = user
        self._dek = unlocked_key(user)
        self._aead = AESGCM(self._dek)
        # Separate key for blind indexes: the DEK is never used for two purposes.
        self._blind_key = HKDF(
            algorithm=hashes.SHA256(), length=32, salt=None, info=b"blind-index"
        ).derive(self._dek)

    def encrypt(self, plaintext: bytes, context: str) -> bytes:
        """Blob format: version(1) | nonce(12) | ciphertext+tag."""
        nonce = os.urandom(NONCE_SIZE)  # fresh per call: reusing a nonce breaks GCM
        ciphertext = self._aead.encrypt(nonce, plaintext, _data_aad(self.user, context))
        return bytes([BLOB_VERSION]) + nonce + ciphertext

    def decrypt(self, blob: bytes, context: str) -> bytes:
        blob = bytes(blob)
        if not blob or blob[0] != BLOB_VERSION:
            raise ValueError("Unsupported blob version.")
        nonce, ciphertext = blob[1 : 1 + NONCE_SIZE], blob[1 + NONCE_SIZE :]
        return self._aead.decrypt(nonce, ciphertext, _data_aad(self.user, context))

    def blind_index(self, data: bytes, context: str) -> bytes:
        """Deterministic 32-byte fingerprint, for equality/dedupe lookups on data
        that is otherwise stored as random-nonce ciphertext."""
        # The NUL separator stops (context, data) pairs from running together.
        mac = hmac.new(self._blind_key, context.encode() + b"\x00" + data, hashlib.sha256)
        return mac.digest()


def encrypt(user, plaintext: bytes, context: str) -> bytes:
    return UserCipher(user).encrypt(plaintext, context)


def decrypt(user, blob: bytes, context: str) -> bytes:
    return UserCipher(user).decrypt(blob, context)


class _Owner:
    """Just enough of a user for UserCipher: its id, which the key registry and the encryption
    context use. Lets a row decrypt its own fields from its `user_id`, without loading the user."""

    __slots__ = ("pk", "id")

    def __init__(self, user_id):
        self.pk = self.id = user_id


def cipher_for(user_id) -> UserCipher:
    """The user's cipher for this request, made once and reused. Model fields that decrypt
    themselves (transactions, categories) use it, so a list of 1,000 rows derives the
    blind-index key once, not 1,000 times. Raises VaultLocked like UserCipher."""
    keys = _unlocked.get()
    cached = keys.get(("cipher", user_id)) if keys is not None else None
    if cached is not None:
        return cached
    cipher = UserCipher(_Owner(user_id))
    if keys is not None:
        keys[("cipher", user_id)] = cipher  # emptied with the keys when the request ends
    return cipher

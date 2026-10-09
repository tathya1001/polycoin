import base64
import hashlib
import hmac
import os

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from django.conf import settings

from .models import UserDataKey

BLOB_VERSION = 1
NONCE_SIZE = 12  # 96 bits, the size GCM is designed for


def _load_keks() -> dict[str, bytes]:
    """Parse FIELD_ENCRYPTION_KEYS ("v1:b64,v2:b64") into {"v1": 32 bytes, ...}."""
    keks = {}
    for item in settings.FIELD_ENCRYPTION_KEYS.split(","):
        version, _, b64 = item.strip().partition(":")
        key = base64.b64decode(b64)
        if not version or len(key) != 32:
            raise ValueError("Each KEK must be 'version:base64' and decode to 32 bytes.")
        keks[version] = key
    return keks


def _wrap_aad(user) -> bytes:
    # Binds a wrapped DEK to its owner: it can't be copied onto another user's row.
    return f"dek:{user.id}".encode()


def _wrap_dek(user, dek: bytes, version: str) -> bytes:
    kek = _load_keks()[version]
    nonce = os.urandom(NONCE_SIZE)
    return nonce + AESGCM(kek).encrypt(nonce, dek, _wrap_aad(user))


def _unwrap_dek(user, record: UserDataKey) -> bytes:
    kek = _load_keks()[record.kek_version]
    wrapped = bytes(record.wrapped_dek)  # Postgres may hand back a memoryview
    nonce, ciphertext = wrapped[:NONCE_SIZE], wrapped[NONCE_SIZE:]
    return AESGCM(kek).decrypt(nonce, ciphertext, _wrap_aad(user))


def create_user_key(user) -> UserDataKey:
    """Generate a fresh DEK for the user and store it wrapped by the active KEK."""
    version = settings.FIELD_ENCRYPTION_ACTIVE_KEY
    wrapped = _wrap_dek(user, os.urandom(32), version)
    return UserDataKey.objects.create(user=user, wrapped_dek=wrapped, kek_version=version)


def _get_dek(user) -> bytes:
    return _unwrap_dek(user, UserDataKey.objects.get(user=user))


def rewrap_user_key(record: UserDataKey) -> bool:
    """Re-wrap a user's DEK under the active KEK. The DEK itself, and therefore
    every blob encrypted with it, is unchanged. Returns False if already current."""
    active = settings.FIELD_ENCRYPTION_ACTIVE_KEY
    if record.kek_version == active:
        return False
    dek = _unwrap_dek(record.user, record)
    record.wrapped_dek = _wrap_dek(record.user, dek, active)
    record.kek_version = active
    record.save(update_fields=["wrapped_dek", "kek_version"])
    return True


def _data_aad(user, context: str) -> bytes:
    # Binds ciphertext to its owner AND the field it belongs to.
    return f"{user.id}:{context}".encode()


class UserCipher:
    """Holds one user's DEK in memory so bulk work (an import, a list response)
    costs a single UserDataKey query instead of one per field."""

    def __init__(self, user):
        self.user = user
        self._dek = _get_dek(user)
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

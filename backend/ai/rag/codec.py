"""The plaintext inside RagDocument.payload_enc: one vector and its text, in one versioned blob.

Format, little-endian: version (1 byte) | dims (uint16) | float16[dims] | utf-8 text.
The first byte lets the format change later without guessing. float16 halves the storage and the
decryption work, and cosine ranking is effectively unchanged at that precision.
"""

import struct

import numpy as np
from django.conf import settings

from ai.models import MAX_DIMS

PAYLOAD_VERSION = 1
_HEADER = struct.Struct("<BH")
_FLOAT16 = np.dtype("<f2")


def max_dims() -> int:
    """settings.RAG_MAX_DIMS, but never above what the database constraint allows."""
    return min(settings.RAG_MAX_DIMS, MAX_DIMS)


def pack(vector, text: str) -> bytes:
    """Raises ValueError for a vector that is empty, too long, or not all finite numbers."""
    try:
        values = np.asarray(vector, dtype=np.float64)
    except (TypeError, ValueError):
        raise ValueError("The vector must be a list of numbers.") from None
    if values.ndim != 1 or values.size == 0:
        raise ValueError("The vector must be a non-empty list of numbers.")
    if values.size > max_dims():
        raise ValueError(f"The vector has more than {max_dims()} dimensions.")
    with np.errstate(over="ignore"):  # too large for float16 becomes inf, rejected just below
        half = values.astype(_FLOAT16)
    if not np.isfinite(half).all():
        raise ValueError("The vector must contain only finite numbers.")
    return _HEADER.pack(PAYLOAD_VERSION, half.size) + half.tobytes() + text.encode()


def unpack(payload: bytes) -> tuple[np.ndarray, str]:
    """One payload back into its read-only float16 vector and its text."""
    if len(payload) < _HEADER.size:
        raise ValueError("The payload is too short.")
    version, dims = _HEADER.unpack_from(payload)
    if version != PAYLOAD_VERSION:
        raise ValueError(f"Unsupported payload version {version}.")
    end = _HEADER.size + dims * _FLOAT16.itemsize
    if len(payload) < end:
        raise ValueError("The payload is truncated.")
    vector = np.frombuffer(payload, dtype=_FLOAT16, count=dims, offset=_HEADER.size)
    return vector, payload[end:].decode()


def unpack_many(payloads: list[bytes], dims: int) -> tuple[np.ndarray, list[str]]:
    """Many payloads of one size into a read-only (n, dims) float16 matrix and the texts, in order.

    The ask path: one pass collects the vector bytes, then one numpy call parses them all. A numpy
    call per row was 1.7x slower at 20k rows.
    """
    header = _HEADER.pack(PAYLOAD_VERSION, dims)
    start = _HEADER.size
    end = start + dims * _FLOAT16.itemsize
    vectors, texts = [], []
    for payload in payloads:
        if payload[:start] != header or len(payload) < end:
            raise ValueError("A payload has another version or size, or is truncated.")
        vectors.append(payload[start:end])
        texts.append(payload[end:].decode())
    matrix = np.frombuffer(b"".join(vectors), dtype=_FLOAT16).reshape(len(payloads), dims)
    return matrix, texts

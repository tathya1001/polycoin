"""The bytes of a Data Backup File.

    polycoin-backup/1\\n<encrypted blob>

The blob is the user's data as gzip-compressed JSON, encrypted with vault.UserCipher: AES-GCM
with the user's own data key, and associated data that names the user and this context. So
only the account that made the file can open it, and any change to it is detected. The key
outlives "Delete my data" and a master-key rotation, so a backup stays usable for the life of
the account.

The short plain-text header says what the file is and which format it uses, so a wrong file
or one from a newer version gets a clear message instead of a failed decryption.
"""

import gzip
import json
import zlib

from cryptography.exceptions import InvalidTag
from django.conf import settings

from vault.services import UserCipher

from .errors import BackupError

MAGIC = b"polycoin-backup/"
FORMAT = 2  # 2 added data sources and transfer links
OLDEST_FORMAT = 1  # the oldest file a restore still reads
CONTEXT = "backup.file"
MAX_HEADER = 32  # bytes before the first newline


def too_large() -> BackupError:
    limit = settings.BACKUP_MAX_BYTES // (1024 * 1024)
    return BackupError("too_large", f"A backup file can be at most {limit} MB.")


def seal(user, data: dict) -> bytes:
    """The file for `data`. Raises BackupError("too_large") when it would be too big to restore."""
    raw = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode()
    packed = gzip.compress(raw, mtime=0)  # mtime 0: no time stamp in the gzip header
    content = MAGIC + str(FORMAT).encode() + b"\n" + UserCipher(user).encrypt(packed, CONTEXT)
    if len(content) > settings.BACKUP_MAX_BYTES:
        raise too_large()
    return content


def _gunzip(packed: bytes, limit: int) -> bytes:
    """Decompress at most `limit` bytes, so a small file can't expand into gigabytes."""
    stream = zlib.decompressobj(16 + zlib.MAX_WBITS)  # 16 +: expect a gzip header
    try:
        raw = stream.decompress(packed, limit + 1)
    except zlib.error:
        raise BackupError("damaged", "The backup file is damaged.") from None
    if len(raw) > limit:
        raise BackupError("too_large", "The backup file holds more data than can be restored.")
    if not stream.eof:
        raise BackupError("damaged", "The backup file is damaged.")
    return raw


def open_file(user, content: bytes) -> dict:
    """The data inside a backup file made by this user's account.

    Raises BackupError: not_a_backup, newer_format, not_your_backup (another account's file,
    or a changed one: AES-GCM can't tell those apart), too_large or damaged.
    """
    if len(content) > settings.BACKUP_MAX_BYTES:
        raise too_large()
    header, newline, blob = content.partition(b"\n")
    if not newline or len(header) > MAX_HEADER or not header.startswith(MAGIC):
        raise BackupError("not_a_backup", "This is not a Polycoin backup file.")
    version = header[len(MAGIC) :]
    if not version.isdigit():
        raise BackupError("not_a_backup", "This is not a Polycoin backup file.")
    if int(version) > FORMAT:
        raise BackupError(
            "newer_format", "This backup was made by a newer version of Polycoin. Reload the page."
        )
    if int(version) < OLDEST_FORMAT:
        raise BackupError("not_a_backup", "This is not a Polycoin backup file.")
    try:
        packed = UserCipher(user).decrypt(blob, CONTEXT)
    except (InvalidTag, ValueError):
        raise BackupError(
            "not_your_backup", "This file is not a backup of this account, or it has been changed."
        ) from None
    try:
        data = json.loads(_gunzip(packed, settings.BACKUP_MAX_JSON_BYTES))
    except (ValueError, UnicodeDecodeError):
        raise BackupError("damaged", "The backup file is damaged.") from None
    if not isinstance(data, dict) or data.get("format") != int(version):
        raise BackupError("damaged", "The backup file is damaged.")
    return data

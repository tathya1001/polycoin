import gzip
import json

import pytest

from backups.errors import BackupError
from backups.fileformat import CONTEXT, FORMAT, MAGIC, open_file, seal
from transactions.tests import make_user
from vault.services import UserCipher

pytestmark = pytest.mark.django_db

DATA = {"format": FORMAT, "transactions": [{"name": "Tastybites Cafe"}]}


@pytest.fixture
def alice():
    return make_user("alice@example.com")


@pytest.fixture
def bob():
    return make_user("bob@example.com")


def code_of(user, content: bytes) -> str:
    with pytest.raises(BackupError) as caught:
        open_file(user, content)
    return caught.value.code


def file_with(user, packed: bytes) -> bytes:
    """A correctly encrypted file around any inner bytes, to test what comes after decryption."""
    return MAGIC + b"1\n" + UserCipher(user).encrypt(packed, CONTEXT)


def test_a_file_opens_for_the_account_that_made_it(alice):
    content = seal(alice, DATA)
    assert content.startswith(b"polycoin-backup/2\n")
    assert open_file(alice, content) == DATA


def test_the_file_hides_the_data(alice):
    assert b"Tastybites" not in seal(alice, DATA)


def test_another_account_cannot_open_it(alice, bob):
    assert code_of(bob, seal(alice, DATA)) == "not_your_backup"


def test_a_changed_byte_is_detected(alice):
    content = bytearray(seal(alice, DATA))
    content[-5] ^= 0x01
    assert code_of(alice, bytes(content)) == "not_your_backup"


@pytest.mark.parametrize(
    "content",
    [
        b"",
        b"PK\x03\x04 an excel file",
        b"polycoin-backup/1",
        b"polycoin-backup/x\n..",
        b"x" * 40 + b"\n",
    ],
)
def test_other_files_are_not_backups(alice, content):
    assert code_of(alice, content) == "not_a_backup"


def test_an_unknown_older_format_is_not_a_backup(alice):
    assert (
        code_of(alice, b"polycoin-backup/0\n" + seal(alice, DATA).split(b"\n", 1)[1])
        == "not_a_backup"
    )


def test_a_newer_format_says_so(alice):
    assert code_of(alice, b"polycoin-backup/3\nanything") == "newer_format"


def test_an_empty_or_short_blob_is_not_yours(alice):
    assert code_of(alice, b"polycoin-backup/1\n") == "not_your_backup"
    assert code_of(alice, b"polycoin-backup/1\n\x01short") == "not_your_backup"


def test_size_is_capped_both_ways(alice, settings):
    content = seal(alice, DATA)
    settings.BACKUP_MAX_BYTES = len(content) - 1
    assert code_of(alice, content) == "too_large"
    with pytest.raises(BackupError) as caught:
        seal(alice, DATA)
    assert caught.value.code == "too_large"


def test_a_small_file_cannot_expand_without_limit(alice, settings):
    settings.BACKUP_MAX_JSON_BYTES = 1024 * 1024
    bomb = gzip.compress(b" " * (5 * 1024 * 1024))  # 5 MB of spaces packs into a few KB
    assert len(bomb) < 20_000
    assert code_of(alice, file_with(alice, bomb)) == "too_large"


@pytest.mark.parametrize(
    "packed",
    [
        b"not gzip at all",
        gzip.compress(b"not json"),
        gzip.compress(b"[1, 2]"),
        gzip.compress(json.dumps({"format": 99}).encode()),
        gzip.compress(json.dumps(DATA).encode())[:-10],  # cut short
    ],
)
def test_damaged_content_is_refused(alice, packed):
    assert code_of(alice, file_with(alice, packed)) == "damaged"

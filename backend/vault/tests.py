"""The vault: per-user data keys locked with the password and a recovery key (Phase 12.1)."""

import base64
import os
import re
from datetime import timedelta

import pytest
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.apps import apps
from django.core.exceptions import ImproperlyConfigured
from django.db import IntegrityError
from django.utils import timezone

import config.settings as production_settings
from accounts.models import User
from vault import services
from vault.models import UserDataKey, VaultSession
from vault.services import (
    KeyUnavailable,
    UserCipher,
    VaultLocked,
    WrongSecret,
    check_keys,
    close_session,
    create_user_key,
    decrypt,
    encrypt,
    forget_unlocked_keys,
    open_session,
    renew_session,
    replace_recovery_key,
    request_scope,
    set_password_lock,
    unlock_session,
    unlock_with_password,
    unlock_with_recovery_key,
    unlocked_key,
)

pytestmark = pytest.mark.django_db

PASSWORD = "x-Str0ng-pass!"
RECOVERY_FORMAT = re.compile(r"^[A-Z2-7]{4}(-[A-Z2-7]{4}){7}$")


def make(email):
    user = User.objects.create_user(email=email, password=PASSWORD)
    user.recovery_key = create_user_key(user, PASSWORD)
    return user


@pytest.fixture
def alice():
    return make("alice@example.com")


@pytest.fixture
def bob():
    return make("bob@example.com")


def record_of(user) -> UserDataKey:
    return UserDataKey.objects.get(user=user)


# --- encrypting with the key ------------------------------------------------------------------


def test_round_trip(alice):
    blob = encrypt(alice, b"4111 1111 1111 1111", "account.number")
    assert decrypt(alice, blob, "account.number") == b"4111 1111 1111 1111"


def test_same_plaintext_gives_different_blobs(alice):
    assert encrypt(alice, b"hello", "ctx") != encrypt(alice, b"hello", "ctx")


def test_tampering_is_detected(alice):
    blob = bytearray(encrypt(alice, b"hello", "ctx"))
    blob[-1] ^= 1  # flip one bit in the tag
    with pytest.raises(InvalidTag):
        decrypt(alice, bytes(blob), "ctx")


def test_other_user_cannot_decrypt(alice, bob):
    blob = encrypt(alice, b"secret", "ctx")
    with pytest.raises(InvalidTag):
        decrypt(bob, blob, "ctx")


def test_wrong_context_fails(alice):
    blob = encrypt(alice, b"secret", "account.number")
    with pytest.raises(InvalidTag):
        decrypt(alice, blob, "account.nickname")


def test_cipher_needs_no_query_once_the_key_is_unlocked(alice, django_assert_num_queries):
    with django_assert_num_queries(0):
        cipher = UserCipher(alice)
        for _ in range(10):
            cipher.decrypt(cipher.encrypt(b"x", "ctx"), "ctx")


def test_blind_index_is_deterministic_and_per_user(alice, bob):
    assert UserCipher(alice).blind_index(b"same", "fp") == UserCipher(alice).blind_index(b"same", "fp")
    assert UserCipher(alice).blind_index(b"same", "fp") != UserCipher(bob).blind_index(b"same", "fp")
    assert UserCipher(alice).blind_index(b"same", "a") != UserCipher(alice).blind_index(b"same", "b")


def test_blind_index_key_is_not_the_data_key(alice):
    cipher = UserCipher(alice)
    assert cipher._blind_key != cipher._dek


# --- the goal: the database alone opens nothing ---------------------------------------------------


def test_a_key_that_is_not_unlocked_cannot_be_used(alice):
    forget_unlocked_keys()
    with pytest.raises(VaultLocked):
        UserCipher(alice)


def test_the_database_holds_no_copy_that_opens_on_its_own(alice, settings):
    dek = unlocked_key(alice)
    record = record_of(alice)
    assert record.wrapped_dek is None and record.kek_version == ""  # no master-key lock
    stored = b"".join(
        bytes(value)
        for value in (record.password_wrapped_dek, record.password_salt, record.recovery_wrapped_dek)
    )
    assert dek not in stored

    # Even with a master key configured, there is nothing for it to open.
    settings.FIELD_ENCRYPTION_KEYS = f"v1:{base64.b64encode(os.urandom(32)).decode()}"
    with pytest.raises(KeyUnavailable):
        services._open_with_master_key(alice, record)


def test_a_key_with_no_lock_at_all_cannot_be_saved(alice):
    with pytest.raises(IntegrityError):
        UserDataKey.objects.filter(user=alice).update(password_wrapped_dek=None)


# --- the password lock (D2, D10, D12) ------------------------------------------------------------


def test_the_password_opens_the_same_key(alice):
    blob = encrypt(alice, b"coffee", "ctx")
    forget_unlocked_keys()
    unlocked = unlock_with_password(alice, PASSWORD)
    assert unlocked.recovery_key is None  # nothing new to show
    assert decrypt(alice, blob, "ctx") == b"coffee"


def test_a_wrong_password_opens_nothing(alice):
    forget_unlocked_keys()
    with pytest.raises(WrongSecret):
        unlock_with_password(alice, "not-the-password")
    with pytest.raises(VaultLocked):
        UserCipher(alice)


def test_each_user_gets_their_own_salt(alice, bob):
    assert bytes(record_of(alice).password_salt) != bytes(record_of(bob).password_salt)


def test_the_lock_records_its_settings(alice):
    assert record_of(alice).kdf_params == "argon2id:t=1,m=8,p=1"  # the tests' fast settings


def test_new_settings_are_applied_at_the_next_unlock(alice, settings):
    blob = encrypt(alice, b"coffee", "ctx")
    settings.VAULT_KDF_TIME_COST = 2
    forget_unlocked_keys()
    unlock_with_password(alice, PASSWORD)
    assert record_of(alice).kdf_params == "argon2id:t=2,m=8,p=1"
    forget_unlocked_keys()
    unlock_with_password(alice, PASSWORD)  # and the re-locked key still opens
    assert decrypt(alice, blob, "ctx") == b"coffee"


def test_a_new_password_lock_replaces_the_old_one_and_keeps_the_recovery_key(alice):
    blob = encrypt(alice, b"coffee", "ctx")
    set_password_lock(alice, unlocked_key(alice), "a-new-Passw0rd")
    forget_unlocked_keys()
    with pytest.raises(WrongSecret):
        unlock_with_password(alice, PASSWORD)
    unlock_with_password(alice, "a-new-Passw0rd")
    assert decrypt(alice, blob, "ctx") == b"coffee"
    forget_unlocked_keys()
    unlock_with_recovery_key(alice, alice.recovery_key)  # D12: unchanged


def test_production_settings_are_at_least_rfc_9106s():
    """The fixture in conftest.py weakens them for speed; the real ones must stay strong."""
    assert production_settings.VAULT_KDF_TIME_COST >= 3
    assert production_settings.VAULT_KDF_MEMORY_KIB >= 64 * 1024
    assert production_settings.VAULT_KDF_PARALLELISM >= 1


# --- the recovery key (D3, D14) -------------------------------------------------------------------


def test_the_recovery_key_is_eight_groups_of_four(alice):
    assert RECOVERY_FORMAT.match(alice.recovery_key)


def test_the_recovery_key_opens_the_same_key(alice):
    blob = encrypt(alice, b"coffee", "ctx")
    forget_unlocked_keys()
    unlock_with_recovery_key(alice, alice.recovery_key)
    assert decrypt(alice, blob, "ctx") == b"coffee"


@pytest.mark.parametrize(
    "rewrite",
    [
        str.lower,
        lambda key: key.replace("-", ""),
        lambda key: " ".join(key.split("-")),
        lambda key: f"  {key}  ",
    ],
)
def test_the_recovery_key_can_be_typed_loosely(alice, rewrite):
    forget_unlocked_keys()
    unlock_with_recovery_key(alice, rewrite(alice.recovery_key))


def test_a_zero_or_one_is_read_as_o_or_i():
    raw = base64.b32decode("OIOIOIOIOIOIOIOIOIOIOIOIOIOIOIOI")
    assert services._recovery_bytes("0101-0101-0101-0101-0101-0101-0101-0101") == raw


@pytest.mark.parametrize("key", ["", "ABCD", "not a key at all", "!" * 39])
def test_a_malformed_recovery_key_opens_nothing(alice, key):
    with pytest.raises(WrongSecret):
        unlock_with_recovery_key(alice, key)


def test_another_users_recovery_key_opens_nothing(alice, bob):
    with pytest.raises(WrongSecret):
        unlock_with_recovery_key(alice, bob.recovery_key)


def test_a_new_recovery_key_replaces_the_old_one(alice):
    new_key = replace_recovery_key(alice, unlocked_key(alice))
    assert new_key != alice.recovery_key and RECOVERY_FORMAT.match(new_key)
    with pytest.raises(WrongSecret):
        unlock_with_recovery_key(alice, alice.recovery_key)
    unlock_with_recovery_key(alice, new_key)


# --- browser sessions (D4, D6, D7) ----------------------------------------------------------------


def test_a_session_opens_the_key_with_its_cookie(alice):
    blob = encrypt(alice, b"coffee", "ctx")
    cookie = open_session(alice, unlocked_key(alice))
    forget_unlocked_keys()
    assert unlock_session(alice, cookie)
    assert decrypt(alice, blob, "ctx") == b"coffee"


def test_the_session_row_alone_opens_nothing(alice):
    open_session(alice, unlocked_key(alice))
    session = VaultSession.objects.get(user=alice)
    forged = f"{session.pk}.{base64.urlsafe_b64encode(os.urandom(32)).decode().rstrip('=')}"
    forget_unlocked_keys()
    assert not unlock_session(alice, forged)


def test_a_session_belongs_to_one_user(alice, bob):
    cookie = open_session(alice, unlocked_key(alice))
    forget_unlocked_keys()
    assert not unlock_session(bob, cookie)


@pytest.mark.parametrize("cookie", [None, "", "garbage", "not-a-uuid.c2VjcmV0", "x.y.z"])
def test_a_malformed_cookie_opens_nothing(alice, cookie):
    assert not unlock_session(alice, cookie)


def test_an_expired_session_opens_nothing(alice):
    cookie = open_session(alice, unlocked_key(alice))
    VaultSession.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
    assert not unlock_session(alice, cookie)
    assert not renew_session(alice.pk, cookie)


def test_closing_a_session_deletes_its_copy(alice):
    cookie = open_session(alice, unlocked_key(alice))
    close_session(cookie)
    assert not VaultSession.objects.filter(user=alice).exists()
    assert not unlock_session(alice, cookie)


def test_renewing_extends_a_session(alice, settings):
    cookie = open_session(alice, unlocked_key(alice))
    VaultSession.objects.update(expires_at=timezone.now() + timedelta(minutes=1))
    assert renew_session(alice.pk, cookie)
    lifetime = settings.SIMPLE_JWT["REFRESH_TOKEN_LIFETIME"]
    assert VaultSession.objects.get().expires_at > timezone.now() + lifetime - timedelta(minutes=1)


def test_opening_a_session_tidies_the_users_expired_ones(alice):
    open_session(alice, unlocked_key(alice))
    VaultSession.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
    open_session(alice, unlocked_key(alice))
    assert VaultSession.objects.filter(user=alice).count() == 1


# --- the per-request registry (D5, D17) -----------------------------------------------------------


def test_keys_opened_in_a_request_are_gone_after_it(alice):
    cookie = open_session(alice, unlocked_key(alice))
    forget_unlocked_keys()
    with request_scope():
        assert unlock_session(alice, cookie)
        UserCipher(alice)
    with pytest.raises(VaultLocked):
        UserCipher(alice)


def test_keys_opened_outside_a_request_are_visible_inside_it(alice):
    with request_scope():
        UserCipher(alice)  # unlocked by create_user_key, outside any request


# --- accounts from before Phase 12.1 (D8, D9) ----------------------------------------------------


def master_key() -> tuple[str, bytes]:
    raw = os.urandom(32)
    return base64.b64encode(raw).decode(), raw


def make_legacy(email, master: bytes):
    """An account as Phase 12 left it: its data key locked with the master key only."""
    user = User.objects.create_user(email=email, password=PASSWORD)
    dek = os.urandom(32)
    nonce = os.urandom(12)
    wrapped = nonce + AESGCM(master).encrypt(nonce, dek, f"dek:{user.id}".encode())
    UserDataKey.objects.create(user=user, wrapped_dek=wrapped, kek_version="v1")
    services._remember(user, dek)
    blob = encrypt(user, b"old data", "ctx")
    forget_unlocked_keys()
    return user, blob


def test_an_old_account_switches_over_at_its_next_login(settings):
    b64, raw = master_key()
    settings.FIELD_ENCRYPTION_KEYS = f"v1:{b64}"
    user, blob = make_legacy("old@example.com", raw)

    unlocked = unlock_with_password(user, PASSWORD)

    assert RECOVERY_FORMAT.match(unlocked.recovery_key)  # shown once
    record = record_of(user)
    assert record.wrapped_dek is None and record.kek_version == ""  # the master lock is erased
    assert decrypt(user, blob, "ctx") == b"old data"

    # The master key is no longer needed: delete it, and everything still opens.
    settings.FIELD_ENCRYPTION_KEYS = ""
    forget_unlocked_keys()
    assert unlock_with_password(user, PASSWORD).recovery_key is None
    assert decrypt(user, blob, "ctx") == b"old data"
    forget_unlocked_keys()
    unlock_with_recovery_key(user, unlocked.recovery_key)
    assert decrypt(user, blob, "ctx") == b"old data"


@pytest.mark.parametrize("configured", ["", "v1:{other}", "v2:{right}"])
def test_an_old_account_without_its_master_key_stays_as_it_was(settings, configured):
    b64, raw = master_key()
    user, _ = make_legacy("old@example.com", raw)
    before = bytes(record_of(user).wrapped_dek)
    other = base64.b64encode(os.urandom(32)).decode()
    settings.FIELD_ENCRYPTION_KEYS = configured.format(other=other, right=b64)

    with pytest.raises(KeyUnavailable):
        unlock_with_password(user, PASSWORD)
    record = record_of(user)
    assert bytes(record.wrapped_dek) == before and record.password_wrapped_dek is None


# --- the master key setting (D9) ------------------------------------------------------------------


def test_no_master_key_is_fine(settings):
    settings.FIELD_ENCRYPTION_KEYS = ""
    check_keys()


def test_a_valid_master_key_is_fine(settings):
    settings.FIELD_ENCRYPTION_KEYS = f"v1:{master_key()[0]}"
    check_keys()


@pytest.mark.parametrize(
    "keys",
    [
        "{key}",  # the base64 without its "v1:" prefix
        "v1:{key},",  # a trailing comma leaves an empty item
        "v1:{short}",  # base64, but 16 bytes
        "v1:not base64 at all!",
        "v1:",
    ],
)
def test_a_malformed_master_key_stops_the_app(settings, keys):
    key, short = master_key()[0], base64.b64encode(os.urandom(16)).decode()
    settings.FIELD_ENCRYPTION_KEYS = keys.format(key=key, short=short)
    with pytest.raises(ImproperlyConfigured) as raised:
        check_keys()
    assert key not in str(raised.value)  # never echo key material into logs
    assert raised.value.__cause__ is None


def test_the_app_runs_the_check_when_django_starts(settings):
    settings.FIELD_ENCRYPTION_KEYS = "missing-prefix"
    with pytest.raises(ImproperlyConfigured):
        apps.get_app_config("vault").ready()

"""The vault: per-user data keys locked with the password and a recovery key (Phase 12.1)."""

import base64
import os
import re
from datetime import timedelta

import pytest
from cryptography.exceptions import InvalidTag
from django.db import IntegrityError
from django.utils import timezone

import config.settings as production_settings
from accounts.models import User
from vault import services
from vault.models import UserDataKey, VaultSession
from vault.services import (
    UserCipher,
    VaultLocked,
    WrongSecret,
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


def test_decrypt_many_opens_like_decrypt_and_keeps_every_check(alice, bob):
    cipher = UserCipher(alice)
    blobs = [cipher.encrypt(f"row {n}".encode(), "ctx") for n in range(3)]
    assert cipher.decrypt_many(blobs, "ctx") == [b"row 0", b"row 1", b"row 2"]
    assert cipher.decrypt_many([memoryview(blobs[0])], "ctx") == [b"row 0"]  # as Postgres gives
    assert cipher.decrypt_many([], "ctx") == []
    tampered = bytearray(blobs[1])
    tampered[-1] ^= 1
    for wrong in (
        lambda: cipher.decrypt_many([blobs[0], bytes(tampered)], "ctx"),
        lambda: cipher.decrypt_many(blobs, "other"),  # wrong context
        lambda: UserCipher(bob).decrypt_many(blobs, "ctx"),  # wrong user
    ):
        with pytest.raises(InvalidTag):
            wrong()
    with pytest.raises(ValueError):
        cipher.decrypt_many([b"\x09" + blobs[0][1:]], "ctx")  # unknown blob version


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


def test_the_database_holds_no_copy_that_opens_on_its_own(alice):
    dek = unlocked_key(alice)
    record = record_of(alice)
    # Every column of the key's row: nothing that opens it without the password or recovery key.
    assert {field.name for field in UserDataKey._meta.fields} == {
        "id", "user", "password_wrapped_dek", "password_salt", "kdf_params",
        "recovery_wrapped_dek", "created_at",
    }  # fmt: skip
    stored = b"".join(
        bytes(value)
        for value in (record.password_wrapped_dek, record.password_salt, record.recovery_wrapped_dek)
    )
    assert dek not in stored


def test_a_key_with_no_lock_at_all_cannot_be_saved(alice):
    with pytest.raises(IntegrityError):
        UserDataKey.objects.filter(user=alice).update(password_wrapped_dek=None)


# --- the password lock (D2, D10, D12) ------------------------------------------------------------


def test_the_password_opens_the_same_key(alice):
    blob = encrypt(alice, b"coffee", "ctx")
    forget_unlocked_keys()
    assert unlock_with_password(alice, PASSWORD) == unlocked_key(alice)
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



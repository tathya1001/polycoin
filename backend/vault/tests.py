import base64
import os

import pytest
from cryptography.exceptions import InvalidTag
from django.apps import apps
from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command

from accounts.models import User
from vault.models import UserDataKey
from vault.services import UserCipher, check_keys, create_user_key, decrypt, encrypt

pytestmark = pytest.mark.django_db


@pytest.fixture
def alice():
    user = User.objects.create_user(email="alice@example.com", password="x-Str0ng-pass!")
    create_user_key(user)
    return user


@pytest.fixture
def bob():
    user = User.objects.create_user(email="bob@example.com", password="x-Str0ng-pass!")
    create_user_key(user)
    return user


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


# --- UserCipher -------------------------------------------------------------


def test_cipher_round_trip(alice):
    cipher = UserCipher(alice)
    blob = cipher.encrypt(b"coffee", "txn.name")
    assert cipher.decrypt(blob, "txn.name") == b"coffee"


def test_cipher_and_module_functions_are_interchangeable(alice):
    cipher = UserCipher(alice)
    assert decrypt(alice, cipher.encrypt(b"x", "ctx"), "ctx") == b"x"
    assert cipher.decrypt(encrypt(alice, b"y", "ctx"), "ctx") == b"y"


def test_cipher_loads_the_key_once(alice, django_assert_num_queries):
    with django_assert_num_queries(1):
        cipher = UserCipher(alice)
    with django_assert_num_queries(0):
        for _ in range(10):
            cipher.decrypt(cipher.encrypt(b"x", "ctx"), "ctx")


def test_cipher_rejects_other_users_blobs(alice, bob):
    blob = UserCipher(alice).encrypt(b"secret", "ctx")
    with pytest.raises(InvalidTag):
        UserCipher(bob).decrypt(blob, "ctx")


# --- Blind index ------------------------------------------------------------


def test_blind_index_is_deterministic_for_one_user(alice):
    a, b = UserCipher(alice), UserCipher(alice)
    assert a.blind_index(b"2026-01-05|debit|4.50", "txn.fp") == b.blind_index(
        b"2026-01-05|debit|4.50", "txn.fp"
    )


def test_blind_index_is_32_bytes_and_differs_for_different_data(alice):
    cipher = UserCipher(alice)
    one = cipher.blind_index(b"one", "txn.fp")
    assert len(one) == 32
    assert one != cipher.blind_index(b"two", "txn.fp")


def test_blind_index_differs_by_context(alice):
    cipher = UserCipher(alice)
    assert cipher.blind_index(b"same", "a") != cipher.blind_index(b"same", "b")


def test_blind_index_differs_across_users(alice, bob):
    assert UserCipher(alice).blind_index(b"same", "txn.fp") != UserCipher(bob).blind_index(
        b"same", "txn.fp"
    )


def test_blind_index_is_not_the_encryption_key_material(alice):
    # The index key is HKDF-derived, so it must differ from the raw DEK.
    cipher = UserCipher(alice)
    assert cipher._blind_key != cipher._dek


# --- KEK rotation -----------------------------------------------------------


def _b64_key():
    return base64.b64encode(os.urandom(32)).decode()


@pytest.fixture
def two_keks(settings):
    """Settings with v1 active and v2 available; users are re-keyed under v1."""
    v1, v2 = _b64_key(), _b64_key()
    settings.FIELD_ENCRYPTION_KEYS = f"v1:{v1},v2:{v2}"
    settings.FIELD_ENCRYPTION_ACTIVE_KEY = "v1"
    return v1, v2


def _rekey_under_active(*users):
    for user in users:
        UserDataKey.objects.filter(user=user).delete()
        create_user_key(user)


def test_rotation_keeps_data_readable_after_old_kek_is_removed(alice, two_keks, settings):
    _rekey_under_active(alice)
    blob = encrypt(alice, b"coffee -4.50", "txn.description")

    settings.FIELD_ENCRYPTION_ACTIVE_KEY = "v2"
    call_command("rotate_kek")
    assert UserDataKey.objects.get(user=alice).kek_version == "v2"

    settings.FIELD_ENCRYPTION_KEYS = f"v2:{two_keks[1]}"  # v1 retired
    assert decrypt(alice, blob, "txn.description") == b"coffee -4.50"


def test_rotation_rewraps_the_key_but_leaves_data_blobs_alone(alice, two_keks, settings):
    _rekey_under_active(alice)
    blob = encrypt(alice, b"secret", "ctx")
    wrapped_before = bytes(UserDataKey.objects.get(user=alice).wrapped_dek)

    settings.FIELD_ENCRYPTION_ACTIVE_KEY = "v2"
    call_command("rotate_kek")

    assert bytes(UserDataKey.objects.get(user=alice).wrapped_dek) != wrapped_before
    assert decrypt(alice, blob, "ctx") == b"secret"  # the old blob still decrypts


def test_blind_index_survives_kek_rotation(alice, two_keks, settings):
    _rekey_under_active(alice)
    before = UserCipher(alice).blind_index(b"same", "txn.fp")

    settings.FIELD_ENCRYPTION_ACTIVE_KEY = "v2"
    call_command("rotate_kek")
    settings.FIELD_ENCRYPTION_KEYS = f"v2:{two_keks[1]}"  # v1 retired

    assert UserCipher(alice).blind_index(b"same", "txn.fp") == before


def test_removing_old_kek_without_rotating_breaks_decryption(alice, two_keks, settings):
    """Why you must rotate BEFORE retiring the old key."""
    _rekey_under_active(alice)
    blob = encrypt(alice, b"secret", "ctx")

    settings.FIELD_ENCRYPTION_KEYS = f"v2:{two_keks[1]}"
    settings.FIELD_ENCRYPTION_ACTIVE_KEY = "v2"
    with pytest.raises(KeyError):
        decrypt(alice, blob, "ctx")


def test_rotation_is_idempotent(alice, bob, two_keks, settings):
    _rekey_under_active(alice, bob)
    settings.FIELD_ENCRYPTION_ACTIVE_KEY = "v2"
    call_command("rotate_kek")
    wrapped = {k.user_id: bytes(k.wrapped_dek) for k in UserDataKey.objects.all()}

    call_command("rotate_kek")  # second run has nothing to do
    assert {k.user_id: bytes(k.wrapped_dek) for k in UserDataKey.objects.all()} == wrapped
    assert set(UserDataKey.objects.values_list("kek_version", flat=True)) == {"v2"}


# --- startup check of the KEK settings ----------------------------------------


def test_valid_keys_pass_the_startup_check(settings):
    settings.FIELD_ENCRYPTION_KEYS = f"v1:{_b64_key()}"
    settings.FIELD_ENCRYPTION_ACTIVE_KEY = "v1"

    check_keys()  # no error


def test_mid_rotation_settings_pass_the_startup_check(two_keks, settings):
    settings.FIELD_ENCRYPTION_ACTIVE_KEY = "v2"  # v1 still listed until rotate_kek has run

    check_keys()


@pytest.mark.parametrize(
    "keys",
    [
        "{key}",  # the first-deploy mistake: the base64 without its "v1:" prefix
        "v1:{key},",  # a trailing comma leaves an empty item
        "v1:{short}",  # base64, but 16 bytes
        "v1:not base64 at all!",
        "v1:",
        "",
    ],
)
def test_malformed_keys_fail_the_startup_check(settings, keys):
    key, short = _b64_key(), base64.b64encode(os.urandom(16)).decode()
    settings.FIELD_ENCRYPTION_KEYS = keys.format(key=key, short=short)
    settings.FIELD_ENCRYPTION_ACTIVE_KEY = "v1"

    with pytest.raises(ImproperlyConfigured) as raised:
        check_keys()

    assert key not in str(raised.value)  # never echo key material into logs
    assert raised.value.__cause__ is None


def test_an_active_key_that_is_not_listed_fails_the_startup_check(settings):
    key = _b64_key()
    settings.FIELD_ENCRYPTION_KEYS = f"v1:{key}"
    settings.FIELD_ENCRYPTION_ACTIVE_KEY = "v2"

    with pytest.raises(ImproperlyConfigured) as raised:
        check_keys()

    assert key not in str(raised.value)


def test_the_app_runs_the_check_when_django_starts(settings):
    settings.FIELD_ENCRYPTION_KEYS = "missing-prefix"

    with pytest.raises(ImproperlyConfigured):
        apps.get_app_config("vault").ready()

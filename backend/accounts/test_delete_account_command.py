"""The delete_account command: deletion for an owner who can no longer sign in."""

from io import StringIO

import pytest
from django.core.management import CommandError, call_command

from transactions.tests import DESCRIPTION, make_user
from vault.models import UserDataKey

from .models import User
from .test_delete_account import fill_everything, row_counts, signed_in

pytestmark = pytest.mark.django_db

EMAIL = "alice@example.com"


def run(*args) -> str:
    out = StringIO()
    call_command("delete_account", *args, stdout=out)
    return out.getvalue()


def answer(monkeypatch, typed):
    monkeypatch.setattr("builtins.input", lambda prompt="": typed)


def test_every_table_is_back_to_what_it_held_before_the_account():
    bob = make_user("bob@example.com")  # another user's rows must survive untouched
    fill_everything(bob)
    signed_in(bob)
    before = row_counts()

    alice = make_user(EMAIL)
    fill_everything(alice)
    signed_in(alice)  # leaves JWT records, which must go too

    output = run(EMAIL, "--no-input")

    assert "Deleted the account" in output
    assert row_counts() == before


def test_typing_the_email_again_deletes(monkeypatch):
    alice = make_user(EMAIL)
    answer(monkeypatch, " ALICE@example.com ")

    run(EMAIL)

    assert not User.objects.filter(pk=alice.pk).exists()
    assert not UserDataKey.objects.filter(user_id=alice.pk).exists()


def test_a_wrong_confirmation_deletes_nothing(monkeypatch):
    alice = make_user(EMAIL)
    fill_everything(alice)
    before = row_counts()
    answer(monkeypatch, "bob@example.com")

    with pytest.raises(CommandError, match="did not match"):
        run(EMAIL)

    assert row_counts() == before


def test_an_unknown_email_deletes_nothing():
    make_user(EMAIL)
    before = row_counts()

    with pytest.raises(CommandError, match="No account"):
        run("nobody@example.com", "--no-input")

    assert row_counts() == before


def test_the_email_is_matched_ignoring_case():
    alice = make_user(EMAIL)

    run("Alice@EXAMPLE.com", "--no-input")

    assert not User.objects.filter(pk=alice.pk).exists()


def test_the_output_shows_counts_never_content():
    alice = make_user(EMAIL)
    fill_everything(alice)

    output = run(EMAIL, "--no-input")

    assert "transactions" in output
    assert DESCRIPTION not in output

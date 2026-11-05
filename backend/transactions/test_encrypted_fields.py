"""Phase 12.2: what a copy of the database shows about a user's money. Nothing, past D16's list.

These read the raw rows with SQL, as someone holding a database dump would."""

from datetime import date
from decimal import Decimal

import pytest
from django.db import IntegrityError, connection, transaction

from categories.models import Category, CategoryKeyword
from categories.testing import category_named
from datasources.models import DataSource
from transactions.models import Transaction, TransferLink
from vault.services import VaultLocked, forget_unlocked_keys

from .tests import make_txn, make_user

pytestmark = pytest.mark.django_db

DAY = date(2026, 3, 14)


@pytest.fixture
def alice():
    return make_user("alice@example.com")


def two_sources(user):
    oak = DataSource.objects.create(user=user, name_index=b"k" * 32, position=0)
    return oak, DataSource.objects.create(user=user, name_index=b"r" * 32, position=1)


def raw_rows(table: str) -> list[tuple]:
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT * FROM {connection.ops.quote_name(table)}")
        return cursor.fetchall()


def columns(table: str) -> set[str]:
    with connection.cursor() as cursor:
        return {c.name for c in connection.introspection.get_table_description(cursor, table)}


def dump(table: str) -> bytes:
    """Every value of every row, as bytes, the way a careless dump would show them."""
    out = b""
    for row in raw_rows(table):
        for value in row:
            out += bytes(value) if isinstance(value, (bytes, memoryview)) else str(value).encode()
            out += b"|"
    return out


def test_a_transaction_row_has_no_readable_date_type_category_or_source(alice):
    food = category_named(alice, "Food")
    txn = make_txn(alice, date=DAY, txn_type="credit", category=food, amount=Decimal("4321.99"))

    table = Transaction._meta.db_table
    assert not {"date", "txn_type", "category_id", "data_source_id"} & columns(table)
    raw = dump(table)
    for secret in (
        b"2026-03-14", b"credit", b"4321.99",  # (created_at may say 2026: D16 allows it)
        str(food.pk).encode(), food.pk.bytes,
        str(txn.data_source_id).encode(), txn.data_source_id.bytes,
    ):  # fmt: skip
        assert secret not in raw


def test_category_names_and_keywords_are_not_readable(alice):
    pets = Category.objects.create(user=alice, name="Veterinary Bills", color="#112233")
    CategoryKeyword.objects.create(category=pets, term="dog grooming")
    assert b"Veterinary" not in dump(Category._meta.db_table)
    assert b"grooming" not in dump(CategoryKeyword._meta.db_table)
    assert b"Food" not in dump(Category._meta.db_table)  # the starter ones too


def test_a_transfer_link_does_not_say_which_side_is_the_debit(alice):
    oak, river = two_sources(alice)
    debit = make_txn(alice, txn_type="debit", data_source=oak)
    credit = make_txn(alice, txn_type="credit", data_source=river, description="in")
    TransferLink.create_between(alice, debit, credit)

    table = TransferLink._meta.db_table
    assert not {"debit_id", "credit_id"} & columns(table)
    link = TransferLink.objects.get()
    # The sides are in id order, whatever the direction.
    assert str(link.first_id) < str(link.second_id)
    assert link.debit_and_credit() == (debit, credit)


def test_nothing_reads_without_the_users_key(alice):
    txn = make_txn(alice)
    category = Category.objects.filter(user=alice).first()
    forget_unlocked_keys()
    fresh = Transaction.objects.get(pk=txn.pk)
    with pytest.raises(VaultLocked):
        fresh.date  # noqa: B018
    with pytest.raises(VaultLocked):
        Category.objects.get(pk=category.pk).name  # noqa: B018


def test_one_source_still_cant_hold_the_same_transaction_twice(alice):
    """D12: the slot keeps this a database rule, though the source is encrypted."""
    make_txn(alice)
    with pytest.raises(IntegrityError), transaction.atomic():
        make_txn(alice)


def test_another_source_can_hold_the_same_transaction(alice):
    oak, river = two_sources(alice)
    first = make_txn(alice, data_source=oak)
    second = make_txn(alice, data_source=river)
    assert first.fingerprint == second.fingerprint and first.slot != second.slot


def test_changing_a_field_re_encrypts_the_core(alice):
    txn = make_txn(alice, date=DAY)
    before = bytes(txn.core_enc)
    txn.date = date(2026, 3, 15)
    txn.save()
    txn.refresh_from_db()
    assert bytes(txn.core_enc) != before
    assert txn.date == date(2026, 3, 15)

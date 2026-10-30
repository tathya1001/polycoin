from datetime import date
from decimal import Decimal
from importlib import import_module
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.db.models import F, ProtectedError
from django.test import override_settings

from accounts.services import delete_user_data
from categories.services import get_default_category, seed_default_categories
from transactions.models import Transaction, TransferLink
from transactions.services import create_transaction
from vault.services import UserCipher, create_user_key

from .models import DataSource
from .services import first_source, seed_default_source

User = get_user_model()

BEFORE = [("transactions", "0004_transaction_notes"), ("datasources", None)]
AFTER = [("transactions", "0006_backfill_data_source"), ("datasources", "0001_initial")]
# The kind of key CI migrates with: a real production DEK could never be unwrapped by it.
THROWAWAY_KEYS = "v1:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="


@pytest.fixture
def alice(db):
    user = User.objects.create_user(email="alice@example.com", password="pw-for-tests-1")
    create_user_key(user)
    seed_default_categories(user)
    return user


def add_row(user, amount="100.00", day=date(2026, 1, 5), kind="debit", **extra):
    return create_transaction(
        UserCipher(user),
        user,
        date=day,
        txn_type=kind,
        name="Tasty Bites",
        description=f"UPI/TASTYBITES/{amount}",
        amount=Decimal(amount),
        balance=None,
        category=get_default_category(user),
        **extra,
    )


# --- a user's first source -----------------------------------------------------------------------


def test_registering_gives_the_user_one_source(client, db):
    response = client.post(
        "/api/accounts/register/",
        {"email": "new@example.com", "password": "a-long-Passw0rd-here"},
        content_type="application/json",
    )
    assert response.status_code == 201
    source = DataSource.objects.get(user__email="new@example.com")
    assert source.name_enc is None  # named on first use, like every first source


def test_seeding_twice_keeps_one_source(alice):
    assert seed_default_source(alice) == seed_default_source(alice)
    assert DataSource.objects.filter(user=alice).count() == 1


def test_first_source_makes_one_for_a_user_who_has_none(alice):
    assert not DataSource.objects.filter(user=alice).exists()
    assert first_source(alice) == DataSource.objects.get(user=alice)


def test_first_source_follows_the_user_order(alice):
    later = DataSource.objects.create(user=alice, name_index=b"b" * 32, position=2)
    earlier = DataSource.objects.create(user=alice, name_index=b"a" * 32, position=1)
    assert first_source(alice) == earlier != later


# --- rows and sources ----------------------------------------------------------------------------


def test_a_new_row_goes_to_the_first_source_by_default(alice):
    assert add_row(alice).data_source == first_source(alice)


def test_a_new_row_can_name_its_source(alice):
    other = DataSource.objects.create(user=alice, name_index=b"o" * 32, position=1)
    assert add_row(alice, data_source=other).data_source == other


def test_a_source_with_rows_cannot_be_deleted_by_accident(alice):
    with pytest.raises(ProtectedError):
        add_row(alice).data_source.delete()


def test_delete_my_data_leaves_one_fresh_source(alice):
    old = add_row(alice).data_source
    other = DataSource.objects.create(user=alice, name_index=b"o" * 32, position=1)
    add_row(alice, amount="9.00", data_source=other)

    counts = delete_user_data(alice)

    assert counts["transactions"] == 2
    source = DataSource.objects.get(user=alice)
    assert source.pk != old.pk and source.name_enc is None


def test_the_transaction_count_ignores_rows_that_go_with_them(alice):
    debit = add_row(alice)
    other = DataSource.objects.create(user=alice, name_index=b"o" * 32, position=1)
    credit = add_row(alice, amount="9.00", kind="credit", data_source=other)
    TransferLink.objects.create(user=alice, debit=debit, credit=credit)

    assert delete_user_data(alice)["transactions"] == 2


# --- transfer links ------------------------------------------------------------------------------


@pytest.fixture
def pair(alice):
    other = DataSource.objects.create(user=alice, name_index=b"o" * 32, position=1)
    return add_row(alice), add_row(alice, kind="credit", data_source=other)


def test_a_row_cannot_be_linked_to_itself(alice, pair):
    with pytest.raises(IntegrityError), transaction.atomic():
        TransferLink.objects.create(user=alice, debit=pair[0], credit=pair[0])


def test_a_row_has_one_partner_at_most(alice, pair):
    debit, credit = pair
    TransferLink.objects.create(user=alice, debit=debit, credit=credit)
    third = add_row(alice, amount="7.00", kind="credit", data_source=credit.data_source)
    with pytest.raises(IntegrityError), transaction.atomic():
        TransferLink.objects.create(user=alice, debit=debit, credit=third)


def test_deleting_a_row_removes_its_link_and_keeps_the_partner(alice, pair):
    debit, credit = pair
    TransferLink.objects.create(user=alice, debit=debit, credit=credit)
    debit.delete()
    assert not TransferLink.objects.exists()
    assert Transaction.objects.filter(pk=credit.pk).exists()


# --- the migrations ------------------------------------------------------------------------------


@pytest.fixture
def old_schema(transactional_db):
    """The database as it was before sources. Puts the latest schema back afterwards."""
    executor = MigrationExecutor(connection)
    executor.migrate(BEFORE)
    state = [BEFORE[0], ("categories", "0005_category_color")]
    yield MigrationExecutor(connection).loader.project_state(state).apps
    executor = MigrationExecutor(connection)
    executor.migrate(executor.loader.graph.leaf_nodes())


def migrate_forward():
    executor = MigrationExecutor(connection)
    executor.migrate(AFTER)
    state = [*AFTER, ("categories", "0005_category_color")]
    return MigrationExecutor(connection).loader.project_state(state).apps


def old_row(apps, user, number: int):
    Category = apps.get_model("categories", "Category")
    category, _ = Category.objects.get_or_create(user=user, name="Others", is_default=True)
    return apps.get_model("transactions", "Transaction").objects.create(
        user=user,
        category=category,
        date=date(2026, 1, 5),
        txn_type="debit",
        name_enc=b"name",
        description_enc=b"description",
        amount_enc=b"amount",
        fingerprint=bytes([number]) * 32,
    )


def old_user(apps, email: str):
    return apps.get_model("accounts", "User").objects.create(email=email, password="unused")


def test_every_row_lands_in_its_owners_first_source(old_schema):
    alice, bob = old_user(old_schema, "a@example.com"), old_user(old_schema, "b@example.com")
    rows = [old_row(old_schema, alice, 1), old_row(old_schema, alice, 2), old_row(old_schema, bob, 3)]
    stamped = {row.pk: row.updated_at for row in rows}

    apps = migrate_forward()

    DataSource_ = apps.get_model("datasources", "DataSource")
    Transaction_ = apps.get_model("transactions", "Transaction")
    assert DataSource_.objects.count() == 2
    assert Transaction_.objects.count() == 3
    assert not Transaction_.objects.filter(data_source__isnull=True).exists()
    assert not Transaction_.objects.exclude(data_source__user_id=F("user_id")).exists()
    # The Ask index compares updated_at: a changed value would embed every row again.
    assert {row.pk: row.updated_at for row in Transaction_.objects.all()} == stamped


def test_a_user_with_no_rows_still_gets_a_source_with_no_name(old_schema):
    old_user(old_schema, "empty@example.com")

    apps = migrate_forward()

    source = apps.get_model("datasources", "DataSource").objects.get()
    assert source.name_enc is None and source.name_index is None


def test_running_the_backfill_again_only_fills_the_gaps(old_schema):
    alice = old_user(old_schema, "a@example.com")
    old_row(old_schema, alice, 1)
    apps = migrate_forward()

    # What the old code writes in the minutes before the new code goes live.
    Transaction_ = apps.get_model("transactions", "Transaction")
    late = Transaction_.objects.get()
    late.pk, late.data_source, late.fingerprint = None, None, b"\x09" * 32
    late.save(force_insert=True)

    import_module("transactions.migrations.0006_backfill_data_source").backfill(apps, None)

    DataSource_ = apps.get_model("datasources", "DataSource")
    assert DataSource_.objects.count() == 1
    assert not Transaction_.objects.filter(data_source__isnull=True).exists()


def test_migrations_never_need_the_production_keys(old_schema):
    """CI migrates with a throwaway key, so nothing here may touch the vault."""
    alice = old_user(old_schema, "a@example.com")  # a user with no key at all
    old_row(old_schema, alice, 1)

    with override_settings(FIELD_ENCRYPTION_KEYS=THROWAWAY_KEYS):
        apps = migrate_forward()

    assert apps.get_model("transactions", "Transaction").objects.get().data_source_id
    backfill = import_module("transactions.migrations.0006_backfill_data_source")
    assert "vault" not in Path(backfill.__file__).read_text()


def test_every_late_row_gets_a_source_before_the_column_becomes_required(old_schema):
    alice = old_user(old_schema, "a@example.com")
    old_row(old_schema, alice, 1)
    apps = migrate_forward()

    # What the previous release's code leaves behind before it stops serving.
    Transaction_ = apps.get_model("transactions", "Transaction")
    late = Transaction_.objects.get()
    late.pk, late.data_source, late.fingerprint = None, None, b"\x09" * 32
    late.save(force_insert=True)
    new_user = old_user(apps, "b@example.com")

    executor = MigrationExecutor(connection)
    executor.migrate(executor.loader.graph.leaf_nodes())

    assert DataSource.objects.filter(user_id=new_user.pk).count() == 1
    assert Transaction.objects.count() == 2


def test_one_statement_can_sit_in_two_sources(alice):
    first = seed_default_source(alice)
    other = DataSource.objects.create(user=alice, name_index=b"o" * 32, position=1)
    add_row(alice, data_source=first)
    add_row(alice, data_source=other)
    assert Transaction.objects.filter(user=alice).count() == 2


def test_one_source_still_refuses_a_duplicate(alice):
    add_row(alice)
    with pytest.raises(IntegrityError), transaction.atomic():
        add_row(alice)

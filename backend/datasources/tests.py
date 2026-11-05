from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction

from accounts.services import delete_user_data
from accounts.testing import confirm_age
from categories.services import get_default_category, seed_default_categories
from transactions.index import in_use
from transactions.links import LinkError, link_transactions
from transactions.models import Transaction, TransferLink
from transactions.services import create_transaction
from vault.services import UserCipher, create_user_key

from .models import DataSource
from .services import first_source, seed_default_source

User = get_user_model()



@pytest.fixture
def alice(db):
    user = User.objects.create_user(email="alice@example.com", password="pw-for-tests-1")
    create_user_key(user, "pw-for-tests-1")
    confirm_age(user)
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
        {"email": "new@example.com", "password": "a-long-Passw0rd-here", "birth_date": "1990-06-15"},
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


def test_a_source_with_rows_is_seen_as_in_use(alice):
    """The database no longer protects it (the source is inside the encrypted core, Phase 12.2,
    D14): the "in use" check reads the cores."""
    row = add_row(alice)
    assert in_use(alice, data_source_id=row.data_source_id) == 1


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
    TransferLink.create_between(alice, debit, credit)

    assert delete_user_data(alice)["transactions"] == 2


# --- transfer links ------------------------------------------------------------------------------


@pytest.fixture
def pair(alice):
    other = DataSource.objects.create(user=alice, name_index=b"o" * 32, position=1)
    return add_row(alice), add_row(alice, kind="credit", data_source=other)


def test_a_row_cannot_be_linked_to_itself(alice, pair):
    with pytest.raises(IntegrityError), transaction.atomic():
        TransferLink.objects.create(user=alice, first=pair[0], second=pair[0])


def test_a_row_has_one_partner_at_most(alice):
    """A row can be either side of a link (Phase 12.2, D15), which no single column constraint
    covers, so the link service checks it, with both rows locked."""
    oak = DataSource.objects.create(user=alice, name_index=b"k" * 32, position=0)
    river = DataSource.objects.create(user=alice, name_index=b"r" * 32, position=1)
    debit = add_row(alice, data_source=oak)
    credit = add_row(alice, kind="credit", data_source=river)
    third = add_row(alice, kind="credit", day=date(2026, 1, 6), data_source=river)
    cipher = UserCipher(alice)
    link_transactions(alice, cipher, debit.pk, credit.pk)
    with pytest.raises(LinkError) as raised:
        link_transactions(alice, cipher, debit.pk, third.pk)
    assert raised.value.code == "already_linked"


def test_deleting_a_row_removes_its_link_and_keeps_the_partner(alice, pair):
    debit, credit = pair
    TransferLink.create_between(alice, debit, credit)
    debit.delete()
    assert not TransferLink.objects.exists()
    assert Transaction.objects.filter(pk=credit.pk).exists()




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

"""Data sources and transfer links in a Data Backup File, and files from before they existed."""

from decimal import Decimal

import pytest

from accounts.services import delete_user_data
from backups.errors import BackupError
from backups.fileformat import open_file, seal
from backups.services import build_backup, restore_backup
from backups.test_services import add_dashboard, history, restore
from datasources.models import MAX_SOURCES_PER_USER
from datasources.services import create_source, first_source, sources_for
from insights.models import Panel
from insights.services import decrypt_config
from transactions.models import Transaction, TransferLink
from transactions.services import remove_source
from transactions.tests import make_txn, make_user
from vault.services import UserCipher

pytestmark = pytest.mark.django_db


@pytest.fixture
def alice():
    return make_user("alice@example.com")


def two_sources(user):
    cipher = UserCipher(user)
    oak = first_source(user)
    river = create_source(user, cipher, "River Bank", "#123456")
    debit = make_txn(user, data_source=oak, description="out", amount=Decimal("50"))
    credit = make_txn(
        user, data_source=river, description="in", amount=Decimal("50"), txn_type="credit"
    )
    TransferLink.objects.create(user=user, debit=debit, credit=credit)
    add_dashboard(
        user,
        "By source",
        panels=[
            (
                "River",
                {
                    "chart": "kpi",
                    "y": {"measure": "spend"},
                    "filters": {"data_sources": [str(river.pk)]},
                },
                {"x": 0, "y": 0, "w": 6, "h": 5},
            )
        ],
    )
    return river


def names_of(user):
    return [source.name for source in sources_for(user, UserCipher(user))]


def test_sources_links_and_panel_filters_come_back(alice):
    two_sources(alice)
    content = build_backup(alice)

    delete_user_data(alice)
    counts = restore_backup(alice, content)

    assert counts["links"] == {"added": 1}
    assert sorted(names_of(alice)) == ["Main", "River Bank"]
    new = next(s for s in sources_for(alice, UserCipher(alice)) if s.name == "River Bank")
    assert new.color == "#123456"
    link = TransferLink.objects.get(user=alice)
    assert link.credit.data_source == new
    panel = Panel.objects.get(dashboard__user=alice)
    config = decrypt_config(UserCipher(alice), panel.config_enc)
    assert config["filters"]["data_sources"] == [str(new.pk)]


def test_restoring_after_renaming_the_first_source_leaves_no_empty_one(alice):
    create_source(alice, UserCipher(alice), "Oak Salary")
    source = next(s for s in sources_for(alice, UserCipher(alice)) if s.name == "Main")
    remove_source(alice, source)
    make_txn(alice, data_source=first_source(alice))
    content = build_backup(alice)

    delete_user_data(alice)
    restore_backup(alice, content)

    assert names_of(alice) == ["Oak Salary"]


def test_restoring_twice_changes_nothing(alice):
    two_sources(alice)
    content = build_backup(alice)
    counts = restore_backup(alice, content)
    assert counts["transactions"] == {"added": 0, "skipped": 2}
    assert counts["data_sources"] == {"added": 0}
    assert counts["links"] == {"added": 0}
    assert TransferLink.objects.filter(user=alice).count() == 1


def test_the_same_statement_in_two_sources_comes_back_in_both(alice):
    river = create_source(alice, UserCipher(alice), "River Bank")
    make_txn(alice, data_source=first_source(alice))
    make_txn(alice, data_source=river)
    content = build_backup(alice)

    delete_user_data(alice)
    restore_backup(alice, content)

    assert Transaction.objects.filter(user=alice).count() == 2


def old_file(user) -> bytes:
    """A file from before data sources: format 1 has no sources, links or row sources."""
    data = open_file(user, build_backup(user))
    for row in data["transactions"]:
        del row["data_source"]
    del data["data_sources"], data["links"]
    data["format"] = 1
    return b"polycoin-backup/1\n" + seal(user, data).split(b"\n", 1)[1]


def test_a_file_from_before_data_sources_goes_into_the_first_source(alice):
    history(alice)
    content = old_file(alice)

    delete_user_data(alice)
    counts = restore_backup(alice, content)

    assert counts["transactions"]["added"] == 3
    assert names_of(alice) == ["Main"]
    assert Transaction.objects.filter(data_source=first_source(alice)).count() == 3


def test_a_row_moved_since_an_old_file_doesnt_come_back_as_a_copy(alice):
    history(alice)
    content = old_file(alice)
    river = create_source(alice, UserCipher(alice), "River Bank")
    Transaction.objects.filter(user=alice).update(data_source=river)

    counts = restore_backup(alice, content)

    assert counts["transactions"] == {"added": 0, "skipped": 3}


def test_a_source_with_a_bad_name_is_damage(alice):
    file = {
        "categories": [],
        "transactions": [],
        "dashboards": [],
        "preferences": {},
        "data_sources": [{"id": "1", "name": "a.b", "color": "#123456"}],
    }
    with pytest.raises(BackupError):
        restore(alice, file)


def test_a_file_at_the_limit_sends_extra_sources_to_the_first(alice):
    two_sources(alice)
    content = build_backup(alice)
    delete_user_data(alice)
    cipher = UserCipher(alice)
    for number in range(MAX_SOURCES_PER_USER - 1):
        create_source(alice, cipher, f"Filler {number}")

    restore_backup(alice, content)

    assert len(names_of(alice)) == MAX_SOURCES_PER_USER
    assert "River Bank" not in names_of(alice)
    assert Transaction.objects.filter(user=alice).count() == 2

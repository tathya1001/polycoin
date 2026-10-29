import json
import logging
from datetime import date
from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction

from accounts.models import UserPreferences
from accounts.services import delete_user_data
from backups.errors import BackupError
from backups.fileformat import FORMAT, open_file, seal
from backups.services import build_backup, file_name, restore_backup
from categories.models import MAX_KEYWORDS_PER_CATEGORY, Category, CategoryKeyword
from insights.models import MAX_DASHBOARDS_PER_USER, Dashboard, Panel
from insights.services import (
    DASHBOARD_NAME,
    PANEL_TITLE,
    decrypt_config,
    decrypt_parameters,
    decrypt_text,
    encrypt_config,
    encrypt_parameters,
    encrypt_text,
)
from transactions.models import Transaction
from transactions.services import create_transaction
from transactions.tests import make_txn, make_user
from vault.services import UserCipher

pytestmark = pytest.mark.django_db


@pytest.fixture
def alice():
    return make_user("alice@example.com")


@pytest.fixture
def bob():
    return make_user("bob@example.com")


def category(user, name):
    return Category.objects.get(user=user, name=name)


def add_dashboard(user, name, panels=(), parameters=None):
    cipher = UserCipher(user)
    dashboard = Dashboard.objects.create(
        user=user,
        name_enc=encrypt_text(cipher, name, DASHBOARD_NAME),
        settings_enc=encrypt_parameters(cipher, parameters) if parameters else None,
        position=Dashboard.objects.filter(user=user).count(),
    )
    for title, config, grid in panels:
        Panel.objects.create(
            dashboard=dashboard,
            title_enc=encrypt_text(cipher, title, PANEL_TITLE),
            config_enc=encrypt_config(cipher, config),
            show_title=title != "Note",
            **grid,
        )
    return dashboard


def history(user):
    """A small account: an own category with a colour and keywords, notes, a row without a
    balance, a dashboard whose panel filters by category, and changed preferences."""
    pets = Category.objects.create(user=user, name="Pets", color="#123456")
    CategoryKeyword.objects.create(category=pets, term="vet")
    CategoryKeyword.objects.create(category=pets, term="kibble")
    food = category(user, "Food")
    cafe = make_txn(user, name="Tastybites Cafe", description="UPI/TASTYBITES/lunch",
                    date=date(2026, 1, 5), amount=Decimal("450.50"), category=food)  # fmt: skip
    make_txn(user, name="Pawsome Clinic", description="UPI/PAWSOME/visit", date=date(2026, 1, 9),
             amount=Decimal("1200"), balance=None, category=pets)  # fmt: skip
    make_txn(user, name="Acme Payroll", description="NEFT/ACME/jan", txn_type="credit",
             date=date(2026, 1, 31), amount=Decimal("5000"), category=category(user, "Salary"))  # fmt: skip
    cafe.notes_enc = UserCipher(user).encrypt(b"team lunch", "txn.notes")
    cafe.save(update_fields=["notes_enc"])

    by_pets = {
        "chart": "bar",
        "x": {"field": "merchant"},
        "y": {"measure": "spend"},
        "filters": {"categories": [str(pets.id), str(food.id)]},
    }
    add_dashboard(
        user,
        "Pet costs",
        panels=[
            ("Pets and food", by_pets, {"x": 0, "y": 0, "w": 6, "h": 5}),
            ("Note", {"chart": "text", "text": "Vet visits"}, {"x": 6, "y": 0, "w": 6, "h": 3}),
        ],
        parameters={"top_n": 5},
    )
    UserPreferences.objects.update_or_create(user=user, defaults={"font": "bitter"})


def snapshot(user) -> dict:
    """Everything a restore should bring back, by name rather than id."""
    cipher = UserCipher(user)
    names = {str(c.id): c.name for c in Category.objects.filter(user=user)}

    def text(blob, context):
        return cipher.decrypt(bytes(blob), context).decode() if blob is not None else None

    rows = sorted(
        (
            t.date.isoformat(),
            t.txn_type,
            t.category.name,
            text(t.name_enc, "txn.name"),
            text(t.description_enc, "txn.description"),
            text(t.amount_enc, "txn.amount"),
            text(t.balance_enc, "txn.balance"),
            text(t.notes_enc, "txn.notes"),
            bytes(t.fingerprint),
        )  # fmt: skip
        for t in Transaction.objects.filter(user=user).select_related("category")
    )
    dashboards = []
    for d in Dashboard.objects.filter(user=user):
        panels = []
        for p in d.panels.all():
            config = decrypt_config(cipher, p.config_enc)
            if "filters" in config:
                config["filters"]["categories"] = sorted(
                    names[pk] for pk in config["filters"]["categories"]
                )
            panels.append(
                (
                    decrypt_text(cipher, p.title_enc, PANEL_TITLE),
                    p.show_title,
                    p.x,
                    p.y,
                    p.w,
                    p.h,
                    json.dumps(config, sort_keys=True),
                )  # fmt: skip
            )
        dashboards.append(
            (
                decrypt_text(cipher, d.name_enc, DASHBOARD_NAME),
                decrypt_parameters(cipher, d.settings_enc),
                sorted(panels),
            )  # fmt: skip
        )
    return {
        "categories": sorted(
            (c.name, c.color, c.is_default, sorted(k.term for k in c.keywords.all()))
            for c in Category.objects.filter(user=user).prefetch_related("keywords")
        ),
        "transactions": rows,
        "dashboards": dashboards,
        "font": UserPreferences.objects.get(user=user).font,
    }


def restore(user, data: dict) -> dict:
    """Restore a backup built from `data` (for files the app itself would never write)."""
    return restore_backup(user, seal(user, {"format": FORMAT, **data}))


# --- the whole round trip ---------------------------------------------------------------


def test_everything_comes_back_after_deleting_the_data(alice):
    history(alice)
    before = snapshot(alice)
    content = build_backup(alice)

    delete_user_data(alice)
    UserPreferences.objects.filter(user=alice).update(font="geist")
    assert not Transaction.objects.filter(user=alice).exists()

    counts = restore_backup(alice, content)
    assert counts == {
        "transactions": {"added": 3, "skipped": 0},
        "categories": {"added": 1},
        "keywords": {"added": 2},
        "dashboards": {"added": 1, "skipped": 0},
        "panels_skipped": 0,
    }
    assert snapshot(alice) == before


def test_panel_filters_point_at_the_new_category_ids(alice):
    history(alice)
    content = build_backup(alice)
    old_pets = str(category(alice, "Pets").id)
    delete_user_data(alice)
    restore_backup(alice, content)

    new_pets = str(category(alice, "Pets").id)
    panel = Panel.objects.get(dashboard__user=alice, show_title=True)
    filters = decrypt_config(UserCipher(alice), panel.config_enc)["filters"]["categories"]
    assert new_pets in filters and old_pets not in filters
    assert set(filters) == {new_pets, str(category(alice, "Food").id)}


def test_restoring_twice_adds_nothing(alice):
    history(alice)
    content = build_backup(alice)
    before = snapshot(alice)
    counts = restore_backup(alice, content)
    assert counts["transactions"] == {"added": 0, "skipped": 3}
    assert counts["dashboards"] == {"added": 0, "skipped": 1}
    assert counts["categories"] == {"added": 0} and counts["keywords"] == {"added": 0}
    assert snapshot(alice) == before


def test_a_restored_row_still_dedupes_against_the_original_statement(alice):
    original = {"date": date(2026, 2, 1), "txn_type": "debit", "name": "Cobalt Cabs",
                "description": "UPI/COBALT/ride", "amount": Decimal("99.00"), "balance": Decimal("10.00")}  # fmt: skip
    cipher = UserCipher(alice)
    row = create_transaction(cipher, alice, category=category(alice, "Others"), **original)
    row.description_enc = cipher.encrypt(b"edited by the user", "txn.description")
    row.save(update_fields=["description_enc"])  # an edit keeps the original fingerprint

    content = build_backup(alice)
    delete_user_data(alice)
    restore_backup(alice, content)

    with pytest.raises(IntegrityError), transaction.atomic():  # what a statement re-import hits
        create_transaction(cipher, alice, category=category(alice, "Others"), **original)


def test_a_backup_holds_only_this_accounts_data_and_no_ask_index(alice, bob):
    history(alice)
    history(bob)
    data = open_file(alice, build_backup(alice))
    assert set(data) == {
        "format",
        "created",
        "app",
        "categories",
        "transactions",
        "dashboards",
        "preferences",
    }
    assert len(data["transactions"]) == 3


# --- merging into an account that has data ---------------------------------------------------


def test_merge_keeps_what_the_account_already_has(alice):
    history(alice)
    content = build_backup(alice)
    pets = category(alice, "Pets")
    pets.color = "#ABCDEF"
    pets.save()
    pets.keywords.filter(term="vet").delete()
    add_dashboard(alice, "Something else")

    counts = restore_backup(alice, content)
    pets.refresh_from_db()
    assert pets.color == "#ABCDEF"  # the account's own colour wins
    assert sorted(k.term for k in pets.keywords.all()) == ["kibble", "vet"]
    assert counts["keywords"] == {"added": 1}
    assert Dashboard.objects.filter(user=alice).count() == 2


def test_keywords_stop_at_the_per_category_limit(alice):
    terms = [f"word{n}" for n in range(MAX_KEYWORDS_PER_CATEGORY + 5)]
    counts = restore(alice, {
        "categories": [{"id": "c1", "name": "Hobbies", "color": "#2A78D6", "is_default": False,
                        "keywords": terms}],
        "transactions": [], "dashboards": [], "preferences": {},
    })  # fmt: skip
    assert counts["keywords"] == {"added": MAX_KEYWORDS_PER_CATEGORY}
    assert category(alice, "Hobbies").keywords.count() == MAX_KEYWORDS_PER_CATEGORY


def test_the_dashboard_limit_is_kept(alice):
    for n in range(MAX_DASHBOARDS_PER_USER):
        add_dashboard(alice, f"Board {n}")
    counts = restore(alice, {
        "categories": [], "transactions": [], "preferences": {},
        "dashboards": [{"name": "One more", "position": 0, "parameters": {}, "panels": []}],
    })  # fmt: skip
    assert counts["dashboards"] == {"added": 0, "skipped": 1}
    assert Dashboard.objects.filter(user=alice).count() == MAX_DASHBOARDS_PER_USER


def test_a_transaction_whose_category_is_missing_goes_to_others(alice):
    restore(alice, {
        "categories": [], "dashboards": [], "preferences": {},
        "transactions": [{"date": "2026-01-01", "txn_type": "debit", "category": "gone",
                          "name": "Riverstone Books", "description": "POS", "amount": "12.00",
                          "balance": None, "notes": None, "fingerprint": "A" * 43 + "="}],
    })  # fmt: skip
    assert Transaction.objects.get(user=alice).category.is_default


def test_a_panel_that_no_longer_fits_is_skipped_and_counted(alice):
    good = {"title": "Spend", "show_title": True, "config": {"chart": "kpi", "y": {"measure": "spend"}},
            "x": 0, "y": 0, "w": 4, "h": 3}  # fmt: skip
    counts = restore(alice, {
        "categories": [], "transactions": [], "preferences": {},
        "dashboards": [{"name": "Mixed", "position": 0, "parameters": {"top_n": 999}, "panels": [
            good,
            {**good, "config": {"chart": "pie", "y": {"measure": "net"}, "x": {"field": "category"}}},
            {**good, "x": 10, "w": 4},  # off the right edge
            {**good, "h": 1},  # too short
            "not a panel",
        ]}],
    })  # fmt: skip
    assert counts["dashboards"] == {"added": 1, "skipped": 0} and counts["panels_skipped"] == 4
    dashboard = Dashboard.objects.get(user=alice)
    assert dashboard.panels.count() == 1
    assert decrypt_parameters(UserCipher(alice), dashboard.settings_enc)["top_n"] == 10  # defaults


def test_an_unknown_font_keeps_the_current_one(alice):
    UserPreferences.objects.update_or_create(user=alice, defaults={"font": "bitter"})
    restore(alice, {"categories": [], "transactions": [], "dashboards": [],
                    "preferences": {"font": "a-font-removed-since", "chart_quality": "performance"}})  # fmt: skip
    preferences = UserPreferences.objects.get(user=alice)
    assert (preferences.font, preferences.chart_quality) == ("bitter", "performance")


# --- refusing a bad file -----------------------------------------------------------------------


def test_another_users_backup_is_refused(alice, bob):
    history(alice)
    with pytest.raises(BackupError) as caught:
        restore_backup(bob, build_backup(alice))
    assert caught.value.code == "not_your_backup"
    assert not Transaction.objects.filter(user=bob).exists()


@pytest.mark.parametrize(
    "bad",
    [
        {"amount": "-5.00"},
        {"amount": "lots"},
        {"amount": "NaN"},
        {"date": "2026-13-01"},
        {"txn_type": "refund"},
        {"fingerprint": "too-short"},
        {"notes": "x" * 501},
        {"name": 5},
    ],
)
def test_a_damaged_row_restores_nothing(alice, bad):
    row = {"date": "2026-01-01", "txn_type": "debit", "category": "c1", "name": "Riverstone Books",
           "description": "POS", "amount": "12.00", "balance": None, "notes": None,
           "fingerprint": "A" * 43 + "="}  # fmt: skip
    data = {
        "categories": [{"id": "c1", "name": "Hobbies", "color": "#2A78D6", "is_default": False, "keywords": []}],
        "transactions": [row, {**row, **bad}], "dashboards": [], "preferences": {},
    }  # fmt: skip
    with pytest.raises(BackupError) as caught:
        restore(alice, data)
    assert caught.value.code == "damaged"
    assert not Category.objects.filter(
        user=alice, name="Hobbies"
    ).exists()  # checked before writing
    assert not Transaction.objects.filter(user=alice).exists()


@pytest.mark.parametrize("missing", ["categories", "transactions", "dashboards", "preferences"])
def test_a_file_missing_a_part_is_damaged(alice, missing):
    data = {"categories": [], "transactions": [], "dashboards": [], "preferences": {}}
    del data[missing]
    with pytest.raises(BackupError) as caught:
        restore(alice, data)
    assert caught.value.code == "damaged"


def test_too_many_transactions_are_refused(alice, settings):
    history(alice)
    content = build_backup(alice)
    settings.BACKUP_MAX_TRANSACTIONS = 2
    with pytest.raises(BackupError) as caught:
        restore_backup(alice, content)
    assert caught.value.code == "too_large"


def test_a_backup_too_big_to_restore_is_never_made(alice, settings):
    history(alice)
    settings.BACKUP_MAX_BYTES = 200
    with pytest.raises(BackupError) as caught:
        build_backup(alice)
    assert caught.value.code == "too_large"


# --- logs and names ----------------------------------------------------------------------------


def test_the_logs_have_counts_but_no_content(alice, caplog):
    history(alice)
    with caplog.at_level(logging.INFO, logger="backups.services"):
        restore_backup(alice, build_backup(alice))
    assert "made a backup: 3 transactions" in caplog.text
    assert "restored a backup" in caplog.text
    for secret in ("Tastybites", "Pawsome", "team lunch", "450.50", "Pets", "Pet costs"):
        assert secret not in caplog.text


def test_the_file_name_has_the_date():
    assert file_name(date(2026, 10, 25)) == "backup-2026-10-25.polycoin"


# --- the bulk loader ---------------------------------------------------------------------------


def test_copy_writes_every_column_of_a_transaction():
    from backups.services import COPY_COLUMNS

    assert sorted(COPY_COLUMNS) == sorted(f.column for f in Transaction._meta.concrete_fields)


def test_an_import_at_the_same_moment_rolls_the_whole_restore_back(alice, monkeypatch):
    history(alice)
    content = build_backup(alice)
    delete_user_data(alice)
    real = UserCipher.encrypt
    raced = []

    def encrypt_while_an_import_runs(self, plaintext, context):
        if context == "txn.name" and not raced:  # first restored row: an import adds it too
            raced.append(True)
            make_txn(alice, name="Tastybites Cafe", description="UPI/TASTYBITES/lunch",
                     date=date(2026, 1, 5), amount=Decimal("450.50"), category=category(alice, "Food"))  # fmt: skip
        return real(self, plaintext, context)

    monkeypatch.setattr(UserCipher, "encrypt", encrypt_while_an_import_runs)
    with pytest.raises(IntegrityError):
        restore_backup(alice, content)
    monkeypatch.undo()
    assert raced
    assert not Category.objects.filter(user=alice, name="Pets").exists()  # nothing was kept
    assert Transaction.objects.filter(user=alice).count() == 0

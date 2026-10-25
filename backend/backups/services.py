"""Making and restoring a Data Backup File.

The file holds everything the user made, decrypted and then encrypted again as one file
(fileformat.py): categories with their colours and keywords, transactions with their notes,
dashboards with their panels and parameters, and the Settings preferences. The "Ask" search
index is left out: the user's own Ollama rebuilds it from the transactions.

A restore merges: it adds only what the account doesn't have, so running it twice changes
nothing. Transactions keep their original fingerprint (the key that made it is the same, since
only this account can open the file), so a later Excel import still finds them as duplicates,
even a row whose text was edited. Categories are matched by name and get new ids, so the
transactions and the panel filters that point at them are mapped onto the new ids.
"""

import base64
import binascii
import json
import logging
import uuid
from datetime import date
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db import connection, transaction
from django.utils import timezone

from accounts.models import UserPreferences
from categories.colors import is_hex_color
from categories.models import (
    MAX_KEYWORD_LENGTH,
    MAX_KEYWORDS_PER_CATEGORY,
    Category,
    CategoryKeyword,
)
from insights.models import (
    GRID_COLUMNS,
    MAX_DASHBOARDS_PER_USER,
    MAX_PANEL_HEIGHT,
    MAX_PANELS_PER_DASHBOARD,
    MIN_PANEL_HEIGHT,
    Dashboard,
    Panel,
)
from insights.serializers import MAX_NAME_LENGTH, MAX_ROW, MAX_TITLE_LENGTH
from insights.services import (
    DASHBOARD_NAME,
    PANEL_CONFIG,
    PANEL_TITLE,
    decrypt_parameters,
    decrypt_text,
    encrypt_config,
    encrypt_parameters,
    encrypt_text,
)
from insights.spec import SpecError
from transactions.models import Transaction
from transactions.serializers import MAX_NOTES_LENGTH
from vault.services import UserCipher

from .errors import BackupError
from .fileformat import FORMAT, open_file, seal

logger = logging.getLogger(__name__)

MAX_CATEGORY_NAME = Category._meta.get_field("name").max_length
MAX_TEXT = 10_000  # a transaction's name or narration; real ones are far shorter
FINGERPRINT_BYTES = 32
# The columns COPY writes, in order; backups/test_services.py checks they are every column.
COPY_COLUMNS = (
    "id", "user_id", "date", "txn_type", "category_id", "name_enc", "description_enc",
    "amount_enc", "balance_enc", "notes_enc", "fingerprint", "created_at", "updated_at",
)  # fmt: skip


def file_name(today: date) -> str:
    return f"backup-{today:%Y-%m-%d}.polycoin"


# --- making a backup -----------------------------------------------------------------


def _b64(data: bytes) -> str:
    return base64.b64encode(bytes(data)).decode()


def _categories(user) -> list[dict]:
    return [
        {
            "id": str(category.id),
            "name": category.name,
            "color": category.color,
            "is_default": category.is_default,
            "keywords": [keyword.term for keyword in category.keywords.all()],
        }
        for category in Category.objects.filter(user=user).prefetch_related("keywords")
    ]


def _transactions(user, cipher: UserCipher) -> list[dict]:
    def text(blob, context):
        return cipher.decrypt(bytes(blob), context).decode()

    rows = (
        Transaction.objects.filter(user=user)
        .order_by("date", "created_at", "id")
        .values_list(
            "date",
            "txn_type",
            "category_id",
            "name_enc",
            "description_enc",
            "amount_enc",
            "balance_enc",
            "notes_enc",
            "fingerprint",
        )  # fmt: skip
    )
    return [
        {
            "date": day.isoformat(),
            "txn_type": txn_type,
            "category": str(category_id),
            "name": text(name, "txn.name"),
            "description": text(description, "txn.description"),
            "amount": text(amount, "txn.amount"),
            "balance": text(balance, "txn.balance") if balance is not None else None,
            "notes": text(notes, "txn.notes") if notes is not None else None,
            "fingerprint": _b64(fingerprint),
        }
        for day, txn_type, category_id, name, description, amount, balance, notes, fingerprint in rows
    ]


def _dashboards(user, cipher: UserCipher) -> list[dict]:
    """Panels keep their config as stored: a config that no longer validates (from an older
    version) is still backed up, and the restore decides what to do with it."""
    dashboards = []
    for dashboard in Dashboard.objects.filter(user=user).prefetch_related("panels"):
        dashboards.append(
            {
                "name": decrypt_text(cipher, dashboard.name_enc, DASHBOARD_NAME),
                "position": dashboard.position,
                "parameters": decrypt_parameters(cipher, dashboard.settings_enc),
                "panels": [
                    {
                        "title": decrypt_text(cipher, panel.title_enc, PANEL_TITLE),
                        "show_title": panel.show_title,
                        "config": json.loads(cipher.decrypt(bytes(panel.config_enc), PANEL_CONFIG)),
                        "x": panel.x,
                        "y": panel.y,
                        "w": panel.w,
                        "h": panel.h,
                    }
                    for panel in dashboard.panels.all()
                ],
            }
        )
    return dashboards


def _preferences(user) -> dict:
    preferences = UserPreferences.objects.filter(user=user).first()
    return {
        "font": preferences.font if preferences else UserPreferences.DEFAULT_FONT,
        "chart_quality": (
            preferences.chart_quality if preferences else UserPreferences.DEFAULT_CHART_QUALITY
        ),
    }


def build_backup(user) -> bytes:
    """The user's Data Backup File. Raises BackupError("too_large") past BACKUP_MAX_BYTES."""
    cipher = UserCipher(user)  # one key load for everything
    data = {
        "format": FORMAT,
        "created": timezone.now().isoformat(),
        "app": settings.GIT_COMMIT,
        "categories": _categories(user),
        "transactions": _transactions(user, cipher),
        "dashboards": _dashboards(user, cipher),
        "preferences": _preferences(user),
    }
    content = seal(user, data)
    logger.info(
        "user %s made a backup: %s transactions, %s dashboards, %s bytes",
        user.pk,
        len(data["transactions"]),
        len(data["dashboards"]),
        len(content),
    )
    return content


# --- reading it back ---------------------------------------------------------------------
# The file can only have been made by this account, but it is checked like any other input:
# an older version may have written it, and a bad value must never reach the database.


def _damaged(part: str) -> BackupError:
    return BackupError("damaged", f"The backup file is damaged ({part}).")


def _text(value, low: int, high: int, part: str) -> str:
    if not isinstance(value, str) or not low <= len(value) <= high:
        raise _damaged(part)
    return value


def _list(data: dict, key: str) -> list:
    value = data.get(key)
    if not isinstance(value, list):
        raise _damaged(key)
    return value


def _money_text(value, part: str, allow_none: bool = False) -> str | None:
    if value is None and allow_none:
        return None
    try:
        amount = Decimal(_text(value, 1, 20, part))
    except InvalidOperation:
        raise _damaged(part) from None
    if not amount.is_finite():
        raise _damaged(part)
    return f"{amount:.2f}"  # the canonical text transactions.services stores


def _clean_categories(raw: list) -> list[dict]:
    clean = []
    for item in raw:
        if not isinstance(item, dict) or not isinstance(item.get("is_default"), bool):
            raise _damaged("categories")
        keywords = item.get("keywords")
        if not isinstance(keywords, list):
            raise _damaged("categories")
        if not is_hex_color(item.get("color")):
            raise _damaged("categories")
        clean.append(
            {
                "id": _text(item.get("id"), 1, 64, "categories"),
                "name": _text(item.get("name"), 1, MAX_CATEGORY_NAME, "categories"),
                "color": item["color"].upper(),
                "is_default": item["is_default"],
                "keywords": [_text(term, 1, MAX_KEYWORD_LENGTH, "keywords") for term in keywords],
            }
        )
    return clean


def _clean_transaction(item) -> dict:
    if not isinstance(item, dict) or item.get("txn_type") not in ("credit", "debit"):
        raise _damaged("transactions")
    try:
        day = date.fromisoformat(_text(item.get("date"), 10, 10, "transactions"))
        fingerprint = base64.b64decode(
            _text(item.get("fingerprint"), 1, 64, "transactions"), validate=True
        )
    except (ValueError, binascii.Error):
        raise _damaged("transactions") from None
    if len(fingerprint) != FINGERPRINT_BYTES:
        raise _damaged("transactions")
    amount = _money_text(item.get("amount"), "transactions")
    if Decimal(amount) <= 0:
        raise _damaged("transactions")
    notes = item.get("notes")
    return {
        "date": day,
        "txn_type": item["txn_type"],
        "category": _text(item.get("category"), 1, 64, "transactions"),
        "name": _text(item.get("name"), 0, MAX_TEXT, "transactions"),
        "description": _text(item.get("description"), 0, MAX_TEXT, "transactions"),
        "amount": amount,
        "balance": _money_text(item.get("balance"), "transactions", allow_none=True),
        "notes": None if notes is None else _text(notes, 1, MAX_NOTES_LENGTH, "transactions"),
        "fingerprint": fingerprint,
    }


def _clean_dashboards(raw: list) -> list[dict]:
    clean = []
    for item in raw:
        if not isinstance(item, dict):
            raise _damaged("dashboards")
        panels = _list(item, "panels")
        if not isinstance(item.get("parameters"), dict):
            raise _damaged("dashboards")
        clean.append(
            {
                "name": " ".join(_text(item.get("name"), 1, MAX_NAME_LENGTH, "dashboards").split()),
                "parameters": item["parameters"],
                "panels": panels,  # checked one by one when restored: a bad one is skipped
            }
        )
    return clean


def _int_in(value, low: int, high: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and low <= value <= high


def _panel_layout_ok(panel) -> bool:
    return (
        isinstance(panel, dict)
        and isinstance(panel.get("title"), str)
        and len(panel["title"]) <= MAX_TITLE_LENGTH
        and isinstance(panel.get("show_title"), bool)
        and isinstance(panel.get("config"), dict)
        and _int_in(panel.get("w"), 1, GRID_COLUMNS)
        and _int_in(panel.get("x"), 0, GRID_COLUMNS - 1)
        and panel["x"] + panel["w"] <= GRID_COLUMNS
        and _int_in(panel.get("y"), 0, MAX_ROW)
        and _int_in(panel.get("h"), MIN_PANEL_HEIGHT, MAX_PANEL_HEIGHT)
    )


def _clean(data: dict) -> dict:
    """Every part of the file checked before anything is written."""
    transactions = _list(data, "transactions")
    if len(transactions) > settings.BACKUP_MAX_TRANSACTIONS:
        raise BackupError(
            "too_large",
            f"A backup can restore at most {settings.BACKUP_MAX_TRANSACTIONS:,} transactions.",
        )
    preferences = data.get("preferences")
    if not isinstance(preferences, dict):
        raise _damaged("preferences")
    return {
        "categories": _clean_categories(_list(data, "categories")),
        "transactions": [_clean_transaction(item) for item in transactions],
        "dashboards": _clean_dashboards(_list(data, "dashboards")),
        "preferences": preferences,
    }


# --- restoring ---------------------------------------------------------------------------


def _restore_categories(user, categories: list[dict]) -> tuple[dict, int, int]:
    """Returns (backup category id -> Category, categories added, keywords added)."""
    existing = list(Category.objects.filter(user=user).prefetch_related("keywords"))
    default = next(category for category in existing if category.is_default)
    by_name = {category.name.lower(): category for category in existing}
    terms = {
        category.id: {k.term.lower() for k in category.keywords.all()} for category in existing
    }
    mapping, added, keywords_added = {}, 0, 0

    for item in categories:
        target = default if item["is_default"] else by_name.get(item["name"].lower())
        if target is None:
            target = Category.objects.create(user=user, name=item["name"], color=item["color"])
            by_name[target.name.lower()] = target
            terms[target.id] = set()
            added += 1
        mapping[item["id"]] = target

        have = terms[target.id]
        new = []
        for term in item["keywords"]:
            if len(have) >= MAX_KEYWORDS_PER_CATEGORY:
                break
            if term.lower() not in have:
                have.add(term.lower())
                new.append(CategoryKeyword(category=target, term=term))
        CategoryKeyword.objects.bulk_create(new)
        keywords_added += len(new)
    return mapping, added, keywords_added


def _restore_transactions(user, cipher: UserCipher, rows: list[dict], mapping: dict) -> int:
    """Adds the rows whose fingerprint the account doesn't have. Returns how many were added.

    The rows go in with PostgreSQL's COPY rather than the ORM's bulk_create: building one
    INSERT for 20,000 rows took most of the time at Render's 0.1 CPU, and COPY is the
    database's own bulk loader. It inserts plain values, so every column is set here. A row an
    import added at the same moment breaks the unique fingerprint, which rolls the whole
    restore back as an IntegrityError.
    """
    have = {
        bytes(fp)
        for fp in Transaction.objects.filter(user=user).values_list("fingerprint", flat=True)
    }
    default = Category.objects.get(user=user, is_default=True)  # for a category not in the file
    now = timezone.now()

    def encrypted(value: str | None, context: str) -> bytes | None:
        return None if value is None else cipher.encrypt(value.encode(), context)

    new = []
    for row in rows:
        if row["fingerprint"] in have:
            continue
        have.add(row["fingerprint"])  # the same row twice in one file counts once
        new.append(
            (
                uuid.uuid4(),
                user.pk,
                row["date"],
                row["txn_type"],
                mapping.get(row["category"], default).pk,
                encrypted(row["name"], "txn.name"),
                encrypted(row["description"], "txn.description"),
                encrypted(row["amount"], "txn.amount"),
                encrypted(row["balance"], "txn.balance"),
                encrypted(row["notes"], "txn.notes"),
                row["fingerprint"],
                now,
                now,
            )
        )
    if new:
        table = connection.ops.quote_name(Transaction._meta.db_table)
        columns = ", ".join(connection.ops.quote_name(column) for column in COPY_COLUMNS)
        # wrap_database_errors: a psycopg error becomes Django's, like any other query's.
        with connection.cursor() as cursor, connection.wrap_database_errors:
            with cursor.copy(f"COPY {table} ({columns}) FROM STDIN") as copy:
                for values in new:
                    copy.write_row(values)
    return len(new)


def _remap_categories(config: dict, mapping: dict) -> dict:
    """The panel's category filter, pointing at this account's category ids."""
    filters = config.get("filters")
    if not isinstance(filters, dict) or not isinstance(filters.get("categories"), list):
        return config
    ids = [str(mapping[old].id) for old in filters["categories"] if old in mapping]
    return {**config, "filters": {**filters, "categories": list(dict.fromkeys(ids))}}


def _restore_dashboards(user, cipher: UserCipher, dashboards: list[dict], mapping: dict):
    """Returns (dashboards added, dashboards skipped, panels skipped)."""
    existing = list(Dashboard.objects.filter(user=user))
    names = {decrypt_text(cipher, d.name_enc, DASHBOARD_NAME).lower() for d in existing}
    count, added, skipped, panels_skipped = len(existing), 0, 0, 0

    for item in dashboards:
        if item["name"].lower() in names or count >= MAX_DASHBOARDS_PER_USER:
            skipped += 1
            continue
        try:
            settings_enc = encrypt_parameters(cipher, item["parameters"])
        except SpecError:
            settings_enc = None  # the defaults
        dashboard = Dashboard.objects.create(
            user=user,
            name_enc=encrypt_text(cipher, item["name"], DASHBOARD_NAME),
            settings_enc=settings_enc,
            position=count,
        )
        panels = []
        for panel in item["panels"]:
            if len(panels) >= MAX_PANELS_PER_DASHBOARD or not _panel_layout_ok(panel):
                panels_skipped += 1
                continue
            try:
                config_enc = encrypt_config(cipher, _remap_categories(panel["config"], mapping))
            except SpecError:  # validated, and upgraded if older, here
                panels_skipped += 1
                continue
            panels.append(
                Panel(
                    dashboard=dashboard,
                    title_enc=encrypt_text(cipher, " ".join(panel["title"].split()), PANEL_TITLE),
                    config_enc=config_enc,
                    show_title=panel["show_title"],
                    x=panel["x"],
                    y=panel["y"],
                    w=panel["w"],
                    h=panel["h"],
                )
            )
        Panel.objects.bulk_create(panels)
        names.add(item["name"].lower())
        count += 1
        added += 1
    return added, skipped, panels_skipped


def _restore_preferences(user, preferences: dict) -> None:
    """Only values this version knows: a font removed since the backup keeps the current one."""
    current, _ = UserPreferences.objects.get_or_create(user=user)
    fonts = {key for key, _ in UserPreferences.FONT_CHOICES}
    qualities = {key for key, _ in UserPreferences.CHART_QUALITY_CHOICES}
    if preferences.get("font") in fonts:
        current.font = preferences["font"]
    if preferences.get("chart_quality") in qualities:
        current.chart_quality = preferences["chart_quality"]
    current.save()


def restore_backup(user, content: bytes) -> dict:
    """Merge a backup into the account, all or nothing. Returns counts only."""
    data = _clean(open_file(user, content))
    rows = data["transactions"]
    with transaction.atomic():
        cipher = UserCipher(user)
        mapping, categories_added, keywords_added = _restore_categories(user, data["categories"])
        transactions_added = _restore_transactions(user, cipher, rows, mapping)
        dashboards_added, dashboards_skipped, panels_skipped = _restore_dashboards(
            user, cipher, data["dashboards"], mapping
        )
        _restore_preferences(user, data["preferences"])

    counts = {
        "transactions": {"added": transactions_added, "skipped": len(rows) - transactions_added},
        "categories": {"added": categories_added},
        "keywords": {"added": keywords_added},
        "dashboards": {"added": dashboards_added, "skipped": dashboards_skipped},
        "panels_skipped": panels_skipped,
    }
    # Counts only: never log what the data was.
    logger.info("user %s restored a backup: %s", user.pk, counts)
    return counts

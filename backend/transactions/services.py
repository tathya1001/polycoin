from datetime import date as date_type
from decimal import Decimal

from django.db import transaction
from django.db.models import F

from datasources.services import SourceError, first_source

from .models import Transaction, TransferLink

CHUNK = 500  # ids or fingerprints in one IN (...): a statement can hold thousands


def _money(value: Decimal) -> str:
    """One canonical text form: Decimal("4.5"), Decimal("4.50") and Decimal("4.500")
    must all become "4.50", or the same transaction would get different fingerprints."""
    return f"{value:.2f}"


def fingerprint_of(
    cipher,
    *,
    date: date_type,
    txn_type: str,
    amount: Decimal,
    balance: Decimal | None,
    description: str,
) -> bytes:
    """Everything that makes two transactions "the same". It does not depend on the data source,
    so the same statement can be recognised in any of them. Including the balance keeps two
    identical coffees on the same day distinct."""
    source = "|".join(
        [
            date.isoformat(),
            txn_type,
            _money(amount),
            _money(balance) if balance is not None else "",
            description,
        ]
    )
    return cipher.blind_index(source.encode(), "txn.fp")


def create_transaction(
    cipher,
    user,
    *,
    date: date_type,
    txn_type: str,
    name: str,
    description: str,
    amount: Decimal,
    balance: Decimal | None,
    category,
    data_source=None,
) -> Transaction:
    """The ONLY write path for transactions (the importer and the tests both use it).
    `cipher` is a vault.services.UserCipher built once per request/import. With no `data_source`
    the row goes to the user's first one; bulk callers pass it, to avoid a query per row."""
    if amount <= 0:
        # The sign lives in txn_type, so the stored amount is always positive.
        raise ValueError("amount must be positive; use txn_type for credit/debit.")

    amount_text = _money(amount)
    balance_text = _money(balance) if balance is not None else None

    return Transaction.objects.create(
        user=user,
        data_source=data_source or first_source(user),
        date=date,
        txn_type=txn_type,
        category=category,
        # A different context string per field: the context is bound into the
        # ciphertext, so a name blob can't be pasted into the description column.
        name_enc=cipher.encrypt(name.encode(), "txn.name"),
        description_enc=cipher.encrypt(description.encode(), "txn.description"),
        amount_enc=cipher.encrypt(amount_text.encode(), "txn.amount"),
        balance_enc=(
            cipher.encrypt(balance_text.encode(), "txn.balance")
            if balance_text is not None
            else None
        ),
        fingerprint=fingerprint_of(
            cipher,
            date=date,
            txn_type=txn_type,
            amount=amount,
            balance=balance,
            description=description,
        ),
    )


def _chunks(items: list):
    for start in range(0, len(items), CHUNK):
        yield items[start : start + CHUNK]


def where_held(user, fingerprints: set[bytes]) -> dict[bytes, set]:
    """{fingerprint: the ids of the user's data sources that hold a row with it}."""
    held: dict[bytes, set] = {}
    for chunk in _chunks(list(fingerprints)):
        rows = Transaction.objects.filter(user=user, fingerprint__in=chunk).order_by()
        for fingerprint, source_id in rows.values_list("fingerprint", "data_source_id"):
            held.setdefault(bytes(fingerprint), set()).add(source_id)
    return held


@transaction.atomic
def move_transactions(user, rows, target) -> tuple[int, int]:
    """Moves `rows` (a queryset of the user's) into the source `target`, and returns how many
    moved and how many stayed because `target` already holds the same transaction.

    Category, notes and everything else stay as they are, and so does updated_at: a row's source
    is not part of its Ask document, so nothing needs embedding again. A link is removed if both
    its rows end up in one source, because a transfer needs two.
    """
    taken = {
        bytes(fingerprint)
        for fingerprint in Transaction.objects.filter(data_source=target)
        .order_by()
        .values_list("fingerprint", flat=True)
    }
    moving, stayed = [], 0
    for pk, fingerprint in rows.exclude(data_source=target).order_by().values_list(
        "pk", "fingerprint"
    ):
        fingerprint = bytes(fingerprint)
        if fingerprint in taken:
            stayed += 1
        else:
            taken.add(fingerprint)
            moving.append(pk)
    for chunk in _chunks(moving):
        Transaction.objects.filter(user=user, pk__in=chunk).update(data_source=target)
    TransferLink.objects.filter(user=user, debit__data_source=F("credit__data_source")).delete()
    return len(moving), stayed


@transaction.atomic
def remove_source(user, source, move_to=None) -> dict:
    """Deletes a data source, with its transactions or after moving them to `move_to`.

    A row that `move_to` already holds is deleted with the source: keeping it would make a
    duplicate. The last source can't go, because an import needs somewhere to put rows.
    """
    if user.datasource_set.count() < 2:
        raise SourceError("last_source", "You need at least one data source.")
    held = Transaction.objects.filter(data_source=source)
    moved = 0
    if move_to is not None:
        moved, _ = move_transactions(user, held, move_to)
    _, per_model = held.delete()
    source.delete()
    return {"moved": moved, "deleted": per_model.get(Transaction._meta.label, 0)}

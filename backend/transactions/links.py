"""Transfer links: two rows that are one movement of the user's own money.

The user approves every link. Amounts are encrypted, so finding a match decrypts them here, over a
bounded date range: the same rule the charts follow.
"""

from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from datetime import date, timedelta

from django.conf import settings
from django.db import IntegrityError, transaction

from datasources.services import sources_for

from .models import Transaction, TransferLink

MAX_CANDIDATES = 20  # shown for one transaction
MAX_SUGGESTIONS = 200  # shown on the review page, which also caps how many one approval sends
SUGGESTION_DAYS = 3  # a transfer arrives within a few days of leaving
SUGGESTION_RANGE_DAYS = 366  # the longest period one request looks through
DEFAULT_CANDIDATE_DAYS = 7
MAX_CANDIDATE_DAYS = 31


class LinkError(ValueError):
    """The two rows can't be linked. `code` is for the UI, the message is for the person."""

    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


class TooManyRows(Exception):
    """The period holds more transactions than one request may decrypt."""


def _unlinked():
    return Transaction.objects.filter(debit_link__isnull=True, credit_link__isnull=True)


def _text(cipher, blob, context: str) -> str:
    return cipher.decrypt(bytes(blob), context).decode()  # bytes(): Postgres gives memoryview


def _check_pair(cipher, first: Transaction, second: Transaction) -> tuple:
    """(debit, credit) if these two can be one transfer. Raises LinkError."""
    if first.txn_type == second.txn_type:
        raise LinkError("same_direction", "Link one debit and one credit.")
    if first.data_source_id == second.data_source_id:
        raise LinkError("same_source", "A transfer joins two different data sources.")
    if _text(cipher, first.amount_enc, "txn.amount") != _text(
        cipher, second.amount_enc, "txn.amount"
    ):
        raise LinkError("different_amount", "A transfer has the same amount on both sides.")
    return (first, second) if first.txn_type == "debit" else (second, first)


def link_transactions(user, cipher, first_id, second_id) -> TransferLink:
    rows = {row.pk: row for row in Transaction.objects.filter(user=user, pk__in=[first_id, second_id])}
    if first_id == second_id or len(rows) != 2:
        raise LinkError("not_found", "Pick two of your transactions.")
    debit, credit = _check_pair(cipher, rows[first_id], rows[second_id])
    try:
        with transaction.atomic():  # one-to-one: a row already linked breaks the constraint
            return TransferLink.objects.create(user=user, debit=debit, credit=credit)
    except IntegrityError:
        raise LinkError("already_linked", "One of these is already linked.") from None


def link_many(user, cipher, pairs: list[dict]) -> dict:
    """Links every pair that can be linked. One bad pair (the rows may have changed since the
    list was shown) never stops the others."""
    linked, failed = 0, []
    for pair in pairs:
        try:
            link_transactions(user, cipher, pair["first"], pair["second"])
            linked += 1
        except LinkError as error:
            failed.append({"first": str(pair["first"]), "second": str(pair["second"]), "code": error.code})
    return {"linked": linked, "failed": failed}


def _describe(row, cipher, names: dict) -> dict:
    return {
        "id": str(row.pk),
        "date": row.date.isoformat(),
        "txn_type": row.txn_type,
        "name": _text(cipher, row.name_enc, "txn.name"),
        "data_source": str(row.data_source_id),
        "data_source_name": names[row.data_source_id],
    }


def link_candidates(user, cipher, row: Transaction, days: int) -> list[dict]:
    """The rows `row` could be linked to, closest in date first."""
    wanted = _text(cipher, row.amount_enc, "txn.amount")
    near = (
        _unlinked()
        .filter(
            user=user,
            date__range=(row.date - timedelta(days=days), row.date + timedelta(days=days)),
        )
        .exclude(txn_type=row.txn_type)
        .exclude(data_source_id=row.data_source_id)
    )
    if near.count() > settings.INSIGHTS_MAX_ROWS:
        raise TooManyRows
    found = [
        other for other in near.defer("description_enc", "balance_enc", "notes_enc")
        if _text(cipher, other.amount_enc, "txn.amount") == wanted
    ]
    found.sort(key=lambda other: (abs((other.date - row.date).days), other.date))
    names = {source.pk: source.name for source in sources_for(user, cipher)}
    return [
        {**_describe(other, cipher, names), "days_apart": abs((other.date - row.date).days)}
        for other in found[:MAX_CANDIDATES]
    ]


@dataclass(frozen=True, slots=True)
class _Side:
    pk: object
    day: date
    source: object


def _split_by_amount(cipher, rows) -> dict:
    """{amount: ([debits], [credits])}, from (pk, date, type, source, amount_enc) rows."""
    sides: dict = {}
    for pk, day, txn_type, source, amount_enc in rows:
        debits, credits = sides.setdefault(_text(cipher, amount_enc, "txn.amount"), ([], []))
        (debits if txn_type == "debit" else credits).append(_Side(pk, day, source))
    return sides


def _likely_pairs(sides: dict) -> list[tuple]:
    """(days apart, date, amount, debit, credit), one partner each, closest pairs first."""
    possible = []
    window = timedelta(days=SUGGESTION_DAYS)
    for amount, (debits, credits) in sides.items():
        credits.sort(key=lambda side: side.day)
        days = [side.day for side in credits]
        for debit in debits:
            low, high = bisect_left(days, debit.day - window), bisect_right(days, debit.day + window)
            possible += [
                (abs((credit.day - debit.day).days), debit.day, amount, debit, credit)
                for credit in credits[low:high]
                if credit.source != debit.source
            ]
    possible.sort(key=lambda pair: pair[:2])

    pairs, used = [], set()
    for pair in possible:
        debit, credit = pair[3], pair[4]
        if debit.pk not in used and credit.pk not in used:
            used |= {debit.pk, credit.pk}
            pairs.append(pair)
    return pairs


def suggest_transfers(user, cipher, start: date, end: date) -> dict:
    """Likely transfers between the user's sources, newest first. Nothing is linked here."""
    rows = _unlinked().filter(user=user, date__range=(start, end)).order_by()
    if rows.count() > settings.INSIGHTS_MAX_ROWS:
        raise TooManyRows

    pairs = _likely_pairs(
        _split_by_amount(
            cipher, rows.values_list("pk", "date", "txn_type", "data_source_id", "amount_enc")
        )
    )
    pairs.sort(key=lambda pair: pair[1], reverse=True)
    shown = pairs[:MAX_SUGGESTIONS]

    ids = [side.pk for pair in shown for side in pair[3:]]
    details = {row.pk: row for row in Transaction.objects.filter(pk__in=ids).order_by()}
    names = {source.pk: source.name for source in sources_for(user, cipher)}
    return {
        "total": len(pairs),
        "pairs": [
            {
                "amount": amount,
                "days_apart": days_apart,
                "debit": _describe(details[debit.pk], cipher, names),
                "credit": _describe(details[credit.pk], cipher, names),
            }
            for days_apart, _, amount, debit, credit in shown
        ],
    }

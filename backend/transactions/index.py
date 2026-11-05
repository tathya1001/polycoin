"""Filtering and sorting transactions in Python (Phase 12.2, D10).

A transaction's date, type, category and source are encrypted (Transaction.core_enc), so the
database can't say "rows in March" or "newest first" any more. This module loads the user's row
ids with their cores, decrypts the cores (about 0.1 s for 20,000 rows on Render's free tier), and
filters and sorts the light `Row`s. Callers then load in full only the rows they keep.
"""

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime

from vault.services import cipher_for

from .models import CORE_CONTEXT, Transaction, decode_core

CHUNK = 2000


@dataclass(frozen=True, slots=True)
class Row:
    id: uuid.UUID
    date: date
    txn_type: str
    category_id: uuid.UUID
    data_source_id: uuid.UUID
    created_at: datetime


def rows_of(user, queryset=None) -> list[Row]:
    """Every transaction of `user` (or of `queryset`, which must hold only theirs), decrypted
    down to its core. Unordered."""
    cipher = cipher_for(user.pk)
    queryset = Transaction.objects.filter(user=user) if queryset is None else queryset
    rows = []
    for pk, blob, created_at in (
        queryset.order_by().values_list("pk", "core_enc", "created_at").iterator(chunk_size=CHUNK)
    ):
        day, txn_type, category_id, source_id = decode_core(cipher.decrypt(blob, CORE_CONTEXT))
        rows.append(Row(pk, day, txn_type, category_id, source_id, created_at))
    return rows


def _newest(row: Row):
    # The order the list always had: newest date first, then newest import, then id, so rows on
    # the same day never swap places between one page and the next.
    return (-row.date.toordinal(), -row.created_at.timestamp(), str(row.id))


def newest_first(rows: Iterable[Row]) -> list[Row]:
    return sorted(rows, key=_newest)


def oldest_first(rows: Iterable[Row]) -> list[Row]:
    return sorted(rows, key=lambda row: (row.date, row.created_at, str(row.id)))


def keep(
    rows: Iterable[Row],
    *,
    start: date | None = None,
    end: date | None = None,
    types=None,
    categories=None,
    sources=None,
) -> list[Row]:
    """The rows inside the period (both ends included) and the given types, categories and
    sources. A filter that is None (or empty) keeps everything."""
    types = set(types) if types else None
    categories = set(categories) if categories else None
    sources = set(sources) if sources else None
    return [
        row
        for row in rows
        if (start is None or row.date >= start)
        and (end is None or row.date <= end)
        and (types is None or row.txn_type in types)
        and (categories is None or row.category_id in categories)
        and (sources is None or row.data_source_id in sources)
    ]


def ids(rows: Iterable[Row]) -> list[uuid.UUID]:
    return [row.id for row in rows]


def load_in_order(queryset, row_ids: list) -> list[Transaction]:
    """The full rows for `row_ids`, in that order (the database returns them in any order)."""
    found = queryset.in_bulk(row_ids)
    return [found[pk] for pk in row_ids if pk in found]


def in_use(user, *, category_id=None, data_source_id=None) -> int:
    """How many of the user's transactions point at this category or source (Phase 12.2, D14)."""
    return sum(
        1
        for row in rows_of(user)
        if (category_id is None or row.category_id == category_id)
        and (data_source_id is None or row.data_source_id == data_source_id)
    )

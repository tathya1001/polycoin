"""Filtering and sorting transactions in Python.

A transaction's date, type, category and source are encrypted (Transaction.core_enc), so the
database can't say "rows in March" or "newest first". This module gives callers every row's core
as light `Row`s to filter and sort; callers then load in full only the rows they keep.

Decrypting 20,000 cores one by one, and parsing them, costs seconds on a small server. So each
user also has a core index (CoreIndex): every core packed into one array and encrypted as one
blob with the same user key. A read decrypts it once and filters and sorts the arrays with numpy;
a `Row` is built only for a row a caller reads. The index is a cache: a database trigger marks it
stale on any change to the user's transactions, and a stale or unreadable index is rebuilt from
the rows, so it can never answer with old data.
"""

import struct
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

import numpy as np
from cryptography.exceptions import InvalidTag
from django.db import connection

from core.db import fetch_binary
from vault.services import cipher_for

from .models import CORE_CONTEXT, Transaction, decode_core

INDEX_CONTEXT = "txn.core-index"
FORMAT = 1
TYPES = ("credit", "debit")
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
# The blob: a header, the distinct category and source ids, then one fixed-size record per row.
# Categories and sources are stored once and referred to by number, which halves the size.
_HEADER = struct.Struct("<BHHI")  # format, categories, sources, rows
_RECORD = np.dtype(
    [
        ("id", "V16"),
        ("day", "<i4"),  # date.toordinal()
        ("type", "u1"),  # index into TYPES
        ("category", "<u2"),
        ("source", "<u2"),
        ("created", "<i8"),  # microseconds since EPOCH
    ]
)
_MICROSECOND = timedelta(microseconds=1)


@dataclass(frozen=True, slots=True)
class Row:
    id: uuid.UUID
    date: date
    txn_type: str
    category_id: uuid.UUID
    data_source_id: uuid.UUID
    created_at: datetime


# --- the packed form -----------------------------------------------------------------------------


def pack(rows: Sequence[Row]) -> bytes:
    categories = list(dict.fromkeys(row.category_id for row in rows))
    sources = list(dict.fromkeys(row.data_source_id for row in rows))
    category_of = {pk: n for n, pk in enumerate(categories)}
    source_of = {pk: n for n, pk in enumerate(sources)}
    records = np.empty(len(rows), dtype=_RECORD)
    records["id"] = np.array([row.id.bytes for row in rows], dtype="V16")
    records["day"] = [row.date.toordinal() for row in rows]
    records["type"] = [TYPES.index(row.txn_type) for row in rows]
    records["category"] = [category_of[row.category_id] for row in rows]
    records["source"] = [source_of[row.data_source_id] for row in rows]
    records["created"] = [(row.created_at - EPOCH) // _MICROSECOND for row in rows]
    return b"".join(
        [
            _HEADER.pack(FORMAT, len(categories), len(sources), len(rows)),
            *(pk.bytes for pk in categories),
            *(pk.bytes for pk in sources),
            records.tobytes(),
        ]
    )


def unpack(data: bytes) -> "CoreRows":
    """CoreRows from `pack`'s bytes. Raises ValueError if they aren't that shape."""
    if len(data) < _HEADER.size:
        raise ValueError("The core index is too short.")
    version, n_categories, n_sources, n_rows = _HEADER.unpack_from(data)
    ids_end = _HEADER.size + 16 * (n_categories + n_sources)
    if version != FORMAT or len(data) != ids_end + n_rows * _RECORD.itemsize:
        raise ValueError("The core index is not in a known format.")
    ids = [uuid.UUID(bytes=data[at : at + 16]) for at in range(_HEADER.size, ids_end, 16)]
    records = np.frombuffer(data, dtype=_RECORD, count=n_rows, offset=ids_end)
    return CoreRows(records, ids[:n_categories], ids[n_categories:])


class CoreRows(Sequence):
    """Rows held as arrays. `keep`, `newest_first` and `oldest_first` work on the arrays; reading
    an item (or iterating) builds the `Row`s, so a caller pays only for the rows it reads."""

    __slots__ = ("_records", "_categories", "_sources")

    def __init__(self, records: np.ndarray, categories: list, sources: list):
        self._records = records
        self._categories = categories
        self._sources = sources

    def __len__(self) -> int:
        return len(self._records)

    def __getitem__(self, key):
        if isinstance(key, slice):
            return self._view(self._records[key])
        position = range(len(self._records))[key]  # IndexError when out of range
        return next(self._rows(self._records[position : position + 1]))

    def __iter__(self):
        return self._rows(self._records)

    def _view(self, records: np.ndarray) -> "CoreRows":
        return CoreRows(records, self._categories, self._sources)

    def _rows(self, records: np.ndarray):
        categories, sources, from_day = self._categories, self._sources, date.fromordinal
        for raw, day, kind, category, source, created in records.tolist():
            yield Row(
                uuid.UUID(bytes=raw),
                from_day(day),
                TYPES[kind],
                categories[category],
                sources[source],
                EPOCH + timedelta(microseconds=created),
            )

    def _numbers(self, wanted: set, ids: list) -> list[int]:
        return [n for n, pk in enumerate(ids) if pk in wanted]

    def keep(self, start=None, end=None, types=None, categories=None, sources=None) -> "CoreRows":
        records = self._records
        mask = np.ones(len(records), dtype=bool)
        if start is not None:
            mask &= records["day"] >= start.toordinal()
        if end is not None:
            mask &= records["day"] <= end.toordinal()
        if types:
            mask &= np.isin(records["type"], [TYPES.index(t) for t in set(types) if t in TYPES])
        if categories:
            mask &= np.isin(records["category"], self._numbers(set(categories), self._categories))
        if sources:
            mask &= np.isin(records["source"], self._numbers(set(sources), self._sources))
        return self._view(records[mask])

    def _sorted(self, newest: bool) -> "CoreRows":
        records = self._records
        # The id breaks ties the way str(uuid) sorts: as two big-endian 64-bit numbers.
        halves = np.frombuffer(records["id"].tobytes(), dtype=">u8").reshape(-1, 2)
        day, created = records["day"].astype(np.int64), records["created"]
        keys = (-day, -created) if newest else (day, created)
        order = np.lexsort((halves[:, 1], halves[:, 0], keys[1], keys[0]))
        return self._view(records[order])

    def newest_first(self) -> "CoreRows":
        return self._sorted(newest=True)

    def oldest_first(self) -> "CoreRows":
        return self._sorted(newest=False)

    def ids(self) -> list[uuid.UUID]:
        return [uuid.UUID(bytes=raw) for raw in self._records["id"].tolist()]

    def category_ids(self) -> list[uuid.UUID]:
        categories = self._categories
        return [categories[n] for n in self._records["category"].tolist()]

    def raw_ids(self) -> list[bytes]:
        return self._records["id"].tolist()

    def only(self, row_ids) -> "CoreRows":
        wanted = _as_raw(row_ids)
        ids = self._records["id"].tolist()
        mask = np.fromiter((raw in wanted for raw in ids), dtype=bool, count=len(ids))
        return self._view(self._records[mask])

    def source_spans(self) -> dict:
        spans = {}
        for n, source in enumerate(self._sources):
            days = self._records["day"][self._records["source"] == n]
            if len(days):
                spans[source] = {
                    "count": len(days),
                    "first": date.fromordinal(int(days.min())),
                    "last": date.fromordinal(int(days.max())),
                }
        return spans

    def count_where(self, category_id=None, data_source_id=None) -> int:
        kept = self.keep(
            categories={category_id} if category_id is not None else None,
            sources={data_source_id} if data_source_id is not None else None,
        )
        return len(kept)


# --- reading -------------------------------------------------------------------------------------


def _decrypt_rows(user, queryset=None) -> list[Row]:
    """Every row of `queryset` (default: all of the user's), decrypted down to its core one by
    one: the index's source. All of a user's rows are fetched with bytea in binary form, which
    halves the bytes and skips Django's hex decoding."""
    if queryset is None:
        found = fetch_binary(
            "SELECT id, core_enc, created_at FROM transactions_transaction WHERE user_id = %s",
            [user.pk],
        )
    else:
        found = list(queryset.order_by().values_list("pk", "core_enc", "created_at"))
    cores = cipher_for(user.pk).decrypt_many([blob for _, blob, _ in found], CORE_CONTEXT)
    return [
        Row(pk, *decode_core(core), created_at) for (pk, _, created_at), core in zip(found, cores)
    ]


def _read_index(user) -> CoreRows | None:
    """The user's core index if it is current and opens, else None."""
    found = fetch_binary(
        "SELECT i.generation, i.built_generation, i.row_count, i.blob, "
        "(SELECT count(*) FROM transactions_transaction t WHERE t.user_id = i.user_id) "
        "FROM transactions_coreindex i WHERE i.user_id = %s",
        [user.pk],
    )
    if not found:
        return None
    generation, built, row_count, blob, actual = found[0]
    if blob is None or built != generation or row_count != actual:
        return None
    try:
        return unpack(cipher_for(user.pk).decrypt(bytes(blob), INDEX_CONTEXT))
    except (InvalidTag, ValueError):
        return None  # tampered with or unreadable: rebuilt below, like a stale one


def _rebuild_index(user) -> CoreRows:
    """Decrypt every row, store the packed cores, and return them.

    The generation is read before the rows. A change that lands while they are read raises it,
    so the store below (which needs it unchanged) is skipped and the next read rebuilds again."""
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO transactions_coreindex (user_id, generation, row_count) "
            "VALUES (%s, 0, 0) ON CONFLICT (user_id) DO NOTHING",
            [user.pk],
        )
        cursor.execute(
            "SELECT generation FROM transactions_coreindex WHERE user_id = %s", [user.pk]
        )
        (generation,) = cursor.fetchone()
    rows = _decrypt_rows(user)
    data = pack(rows)
    blob = cipher_for(user.pk).encrypt(data, INDEX_CONTEXT)
    # Stored only if nothing changed meanwhile, and never by waiting: while an import is still
    # writing, its transaction holds the row, and this request skips the store instead of
    # hanging until the import ends. The index is a cache; the next read builds it again.
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE transactions_coreindex SET blob = %s, built_generation = %s, row_count = %s "
            "WHERE user_id = (SELECT user_id FROM transactions_coreindex "
            "WHERE user_id = %s AND generation = %s FOR UPDATE SKIP LOCKED)",
            [blob, generation, len(rows), user.pk, generation],
        )
    return unpack(data)


def rows_of(user, queryset=None) -> Sequence[Row]:
    """Every transaction of `user` (or of `queryset`, which must hold only theirs), decrypted
    down to its core. Unordered."""
    if queryset is not None:
        return _decrypt_rows(user, queryset)
    current = _read_index(user)
    return current if current is not None else _rebuild_index(user)


# --- filtering and sorting -----------------------------------------------------------------------


def _newest(row: Row):
    # The order the list always had: newest date first, then newest import, then id, so rows on
    # the same day never swap places between one page and the next.
    return (-row.date.toordinal(), -row.created_at.timestamp(), str(row.id))


def newest_first(rows: Iterable[Row]) -> Sequence[Row]:
    if isinstance(rows, CoreRows):
        return rows.newest_first()
    return sorted(rows, key=_newest)


def oldest_first(rows: Iterable[Row]) -> Sequence[Row]:
    if isinstance(rows, CoreRows):
        return rows.oldest_first()
    return sorted(rows, key=lambda row: (row.date, row.created_at, str(row.id)))


def keep(
    rows: Iterable[Row],
    *,
    start: date | None = None,
    end: date | None = None,
    types=None,
    categories=None,
    sources=None,
) -> Sequence[Row]:
    """The rows inside the period (both ends included) and the given types, categories and
    sources. A filter that is None (or empty) keeps everything."""
    if isinstance(rows, CoreRows):
        return rows.keep(start, end, types, categories, sources)
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
    if isinstance(rows, CoreRows):
        return rows.ids()
    return [row.id for row in rows]


def category_ids(rows: Iterable[Row]) -> list[uuid.UUID]:
    """Each row's category id, in the rows' order."""
    if isinstance(rows, CoreRows):
        return rows.category_ids()
    return [row.category_id for row in rows]


def raw_ids(rows: Iterable[Row]) -> list[bytes]:
    """Each row's id as its 16 bytes, in the rows' order: cheaper than UUIDs to look up."""
    if isinstance(rows, CoreRows):
        return rows.raw_ids()
    return [row.id.bytes for row in rows]


def _as_raw(row_ids) -> set[bytes]:
    return {pk if isinstance(pk, bytes) else pk.bytes for pk in row_ids}


def only(rows: Iterable[Row], row_ids) -> Sequence[Row]:
    """The rows whose id is in `row_ids` (UUIDs, or their 16 bytes), in their order."""
    if isinstance(rows, CoreRows):
        return rows.only(row_ids)
    wanted = _as_raw(row_ids)
    return [row for row in rows if row.id.bytes in wanted]


def source_spans(rows: Iterable[Row]) -> dict:
    """{source id: {"count", "first", "last"}}: each source's rows and first and last date."""
    if isinstance(rows, CoreRows):
        return rows.source_spans()
    spans: dict = {}
    for row in rows:
        span = spans.setdefault(
            row.data_source_id, {"count": 0, "first": row.date, "last": row.date}
        )
        span["count"] += 1
        span["first"], span["last"] = min(span["first"], row.date), max(span["last"], row.date)
    return spans


def load_in_order(queryset, row_ids: list) -> list[Transaction]:
    """The full rows for `row_ids`, in that order (the database returns them in any order)."""
    found = queryset.in_bulk(row_ids)
    return [found[pk] for pk in row_ids if pk in found]


def in_use(user, *, category_id=None, data_source_id=None) -> int:
    """How many of the user's transactions point at this category or source."""
    rows = rows_of(user)
    if isinstance(rows, CoreRows):
        return rows.count_where(category_id=category_id, data_source_id=data_source_id)
    return sum(
        1
        for row in rows
        if (category_id is None or row.category_id == category_id)
        and (data_source_id is None or row.data_source_id == data_source_id)
    )

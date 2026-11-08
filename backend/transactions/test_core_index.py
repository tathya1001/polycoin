"""The core index (transactions/index.py): one encrypted blob of every row's core, as a cache."""

import random
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from django.db import connection

from categories.models import Category
from categories.services import get_default_category
from transactions import index
from transactions.index import (
    CoreRows,
    Row,
    keep,
    newest_first,
    oldest_first,
    pack,
    rows_of,
    unpack,
)
from transactions.models import CoreIndex, Transaction
from transactions.tests import make_txn, make_user

pytestmark = pytest.mark.django_db


@pytest.fixture
def alice():
    return make_user("alice@example.com")


def _rows(count: int, seed: int = 1) -> list[Row]:
    """Rows with many ties on date and import time, so the id has to break them."""
    rng = random.Random(seed)
    categories = [uuid.uuid4() for _ in range(4)]
    sources = [uuid.uuid4() for _ in range(2)]
    start = datetime(2026, 1, 1, tzinfo=UTC)
    return [
        Row(
            uuid.uuid4(),
            date(2026, 1, 1) + timedelta(days=rng.randrange(10)),
            rng.choice(("credit", "debit")),
            rng.choice(categories),
            rng.choice(sources),
            start + timedelta(microseconds=rng.randrange(3)),
        )
        for _ in range(count)
    ]


def _txns(user, count: int) -> list[Transaction]:
    return [
        make_txn(user, date=date(2026, 1, 1) + timedelta(days=n), amount=Decimal(f"{n + 1}.00"))
        for n in range(count)
    ]


def _state(user) -> CoreIndex:
    return CoreIndex.objects.get(user=user)


def _other_category(user) -> Category:
    return Category.objects.filter(user=user).exclude(pk=get_default_category(user).pk).first()


# --- the packed form -----------------------------------------------------------------------------


def test_packing_keeps_every_field_of_every_row():
    rows = _rows(50)
    assert list(unpack(pack(rows))) == rows
    assert list(unpack(pack([]))) == []


@pytest.mark.parametrize(
    "data",
    [b"", b"\x01", b"\x02" + bytes(8), pack(_rows(3))[:-1], pack(_rows(3)) + b"\x00"],
    ids=["empty", "short", "unknown format", "cut short", "too long"],
)
def test_bytes_that_arent_a_packed_index_are_refused(data):
    with pytest.raises(ValueError):
        unpack(data)


def test_filtering_and_sorting_the_arrays_matches_the_rows_one_by_one():
    rows = _rows(300)
    packed = unpack(pack(rows))
    some_categories = {rows[0].category_id, rows[1].category_id}
    filters = [
        {},
        {"start": date(2026, 1, 3), "end": date(2026, 1, 6)},
        {"types": ["debit"]},
        {"categories": some_categories, "sources": {rows[2].data_source_id}},
        {"categories": {uuid.uuid4()}},  # no row has it
        {"types": set()},  # empty: keeps everything
    ]
    for given in filters:
        assert list(keep(packed, **given)) == keep(rows, **given), given
    assert list(newest_first(packed)) == newest_first(rows)
    assert list(oldest_first(packed)) == oldest_first(rows)
    assert list(newest_first(keep(packed, types=["credit"]))) == newest_first(
        keep(rows, types=["credit"])
    )


def test_the_arrays_behave_like_a_list():
    rows = newest_first(_rows(10))
    packed = newest_first(unpack(pack(rows)))
    assert isinstance(packed, CoreRows)
    assert len(packed) == 10 and packed[0] == rows[0] and packed[-1] == rows[-1]
    assert list(packed[2:5]) == rows[2:5]
    assert index.ids(packed) == [row.id for row in rows]
    with pytest.raises(IndexError):
        packed[10]
    assert not unpack(pack([]))


# --- reading through the index -------------------------------------------------------------------


def test_the_first_read_builds_the_index_and_later_reads_use_it(alice, django_assert_num_queries):
    _txns(alice, 3)
    first = rows_of(alice)
    state = _state(alice)
    assert state.built_generation == state.generation and state.row_count == 3
    assert sorted(first, key=str) == sorted(
        index._decrypt_rows(alice, Transaction.objects.filter(user=alice)), key=str
    )
    with django_assert_num_queries(0):  # one psycopg query, outside Django's query log
        again = rows_of(alice)
    assert list(again) == list(first)


def test_the_stored_index_is_encrypted(alice):
    txn = _txns(alice, 1)[0]
    rows_of(alice)
    blob = bytes(_state(alice).blob)
    assert txn.id.bytes not in blob and txn.category_id.bytes not in blob


@pytest.mark.parametrize("change", ["save", "bulk_create", "bulk_update", "delete", "queryset"])
def test_every_kind_of_write_marks_the_index_stale_and_the_next_read_sees_it(alice, change):
    txns = _txns(alice, 3)
    rows_of(alice)
    before = _state(alice).generation
    food = _other_category(alice)

    if change == "save":
        txns[0].category = food
        txns[0].save()
    elif change == "bulk_create":
        make_txn(alice, amount=Decimal("99.00"))  # create_transaction inserts in bulk
    elif change == "bulk_update":
        for txn in txns:
            txn.category = food
            txn.seal()
        Transaction.objects.bulk_update(txns, ["core_enc", "slot"])
    elif change == "delete":
        txns[0].delete()
    else:
        Transaction.objects.filter(pk__in=[t.pk for t in txns[:2]]).delete()

    assert _state(alice).generation > before
    fresh = index._decrypt_rows(alice, Transaction.objects.filter(user=alice))
    assert sorted(rows_of(alice), key=str) == sorted(fresh, key=str)
    state = _state(alice)
    assert state.built_generation == state.generation


def test_the_triggers_exist():
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT tgname FROM pg_trigger WHERE tgrelid = 'transactions_transaction'::regclass "
            "AND tgname LIKE 'txn_core_index_%%'"
        )
        names = {name for (name,) in cursor.fetchall()}
    assert names == {"txn_core_index_insert", "txn_core_index_update", "txn_core_index_delete"}


def test_a_row_count_that_doesnt_match_forces_a_rebuild(alice):
    # A second guard, should the trigger ever be missing: the row count is checked every read.
    _txns(alice, 2)
    rows_of(alice)
    CoreIndex.objects.filter(user=alice).update(row_count=5)
    assert len(rows_of(alice)) == 2
    assert _state(alice).row_count == 2


def test_a_tampered_index_is_rebuilt_not_trusted(alice):
    _txns(alice, 2)
    rows_of(alice)
    blob = bytearray(_state(alice).blob)
    blob[-1] ^= 1
    CoreIndex.objects.filter(user=alice).update(blob=bytes(blob))
    assert len(rows_of(alice)) == 2


def test_one_users_index_never_opens_for_another():
    alice, bob = make_user("alice@example.com"), make_user("bob@example.com")
    _txns(alice, 3)
    _txns(bob, 1)
    rows_of(alice), rows_of(bob)
    stolen = _state(alice)
    CoreIndex.objects.filter(user=bob).update(
        blob=stolen.blob, row_count=1, built_generation=_state(bob).generation
    )
    rows = rows_of(bob)  # the key and context don't match: rebuilt from bob's own rows
    assert [row.id for row in rows] == list(
        Transaction.objects.filter(user=bob).values_list("pk", flat=True)
    )


def test_a_change_during_a_rebuild_is_not_stored_as_current(alice, monkeypatch):
    _txns(alice, 2)
    real = index._decrypt_rows

    def changed_meanwhile(user, queryset=None):
        rows = real(user, queryset)
        make_txn(alice, amount=Decimal("77.00"))  # lands after the generation was read
        return rows

    monkeypatch.setattr(index, "_decrypt_rows", changed_meanwhile)
    assert len(rows_of(alice)) == 2  # this read's own view
    monkeypatch.setattr(index, "_decrypt_rows", real)
    assert _state(alice).built_generation != _state(alice).generation  # not stored
    assert len(rows_of(alice)) == 3  # the next read rebuilds


def test_a_user_with_no_transactions_has_an_empty_index(alice):
    assert list(rows_of(alice)) == []
    state = _state(alice)
    assert state.built_generation == state.generation and state.row_count == 0
    assert list(rows_of(alice)) == []


def test_deleting_a_user_with_transactions_and_an_index_works(alice):
    _txns(alice, 2)
    rows_of(alice)
    alice.delete()
    assert not CoreIndex.objects.exists() and not Transaction.objects.exists()


def test_counting_rows_per_category_and_source(alice):
    txns = _txns(alice, 3)
    food = _other_category(alice)
    txns[0].category = food
    txns[0].save()
    assert index.in_use(alice, category_id=food.pk) == 1
    assert index.in_use(alice, data_source_id=txns[0].data_source_id) == 3
    assert index.in_use(alice, category_id=uuid.uuid4()) == 0


def test_the_array_helpers_match_the_rows_one_by_one():
    rows = _rows(200, seed=3)
    packed = unpack(pack(rows))
    wanted = {rows[5].id, rows[17].id, uuid.uuid4()}
    assert list(index.only(packed, wanted)) == index.only(rows, wanted)
    assert index.category_ids(packed) == index.category_ids(rows)
    assert index.source_spans(packed) == index.source_spans(rows)
    assert index.source_spans(unpack(pack([]))) == {}


def test_dashboard_rows_in_stored_order_come_from_the_index(alice):
    from insights.services import load_rows

    txns = _txns(alice, 3)
    rows_of(alice)  # the index is current, so load_rows reads arrays
    loaded = load_rows(
        alice, date(2026, 1, 1), date(2026, 1, 31), need=frozenset({"stored_order", "id"})
    )
    assert [row["id"] for row in loaded] == [t.pk for t in sorted(txns, key=lambda t: t.created_at)]


def test_raw_ids_and_only_take_uuids_or_their_bytes():
    rows = _rows(20, seed=5)
    packed = unpack(pack(rows))
    assert index.raw_ids(packed) == [row.id.bytes for row in rows] == index.raw_ids(rows)
    wanted = {rows[3].id, rows[7].id}
    as_bytes = {pk.bytes for pk in wanted}
    assert list(index.only(packed, as_bytes)) == list(index.only(packed, wanted))
    assert index.only(rows, as_bytes) == index.only(rows, wanted) == [rows[3], rows[7]]


def test_a_uuid_array_literal_holds_only_hex_and_finds_the_rows(alice):
    from core.db import fetch_binary, uuid_array

    txns = _txns(alice, 3)
    literal = uuid_array([txns[0].id.bytes, txns[2].id.bytes])
    assert set(literal) <= set("{},0123456789abcdef")
    found = fetch_binary(
        "SELECT uuid_send(id) FROM transactions_transaction WHERE id = ANY(%s::uuid[])", [literal]
    )
    assert {raw for (raw,) in found} == {txns[0].id.bytes, txns[2].id.bytes}
    assert fetch_binary("SELECT 1 WHERE %s::uuid[] = '{}'", [uuid_array([])]) == [(1,)]


@pytest.mark.django_db(transaction=True)
def test_a_rebuild_never_waits_for_a_write_still_in_progress():
    """While another transaction (an import) holds the index row, a read still answers from the
    rows and skips storing, instead of hanging until the import ends."""
    import psycopg

    alice = make_user("alice@example.com")
    _txns(alice, 2)
    rows_of(alice)
    make_txn(alice, amount=Decimal("55.00"))  # stale now
    db = connection.settings_dict
    with psycopg.connect(
        dbname=db["NAME"], user=db["USER"], password=db["PASSWORD"], host=db["HOST"],
        port=db["PORT"] or None, autocommit=False,
    ) as other:  # fmt: skip
        other.execute(
            "SELECT 1 FROM transactions_coreindex WHERE user_id = %s FOR UPDATE", [alice.pk]
        )
        with connection.cursor() as cursor:
            cursor.execute("SET statement_timeout = '5s'")  # a wait would fail, not hang
        assert len(rows_of(alice)) == 3
        assert _state(alice).built_generation != _state(alice).generation  # not stored
        other.rollback()
    with connection.cursor() as cursor:
        cursor.execute("SET statement_timeout = 0")
    assert len(rows_of(alice)) == 3
    assert _state(alice).built_generation == _state(alice).generation

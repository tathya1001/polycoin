"""Opt-in speed check of `rows_of`: every transaction of a user, decrypted down to its core.

Every list, dashboard, search and panel preview starts here, so its cost at 20,000 rows on the
server's 0.1 CPU decides how fast they all are. Seeds one fictional user (seeding takes a while),
then times each part: fetching the rows, decrypting the cores, parsing them, building `Row`s,
sorting newest first.

1. A quick estimate with no limits; CPU time is scaled to 0.1 CPU:

       docker compose exec -e INDEX_PERF=1 backend pytest transactions/test_index_performance.py -s

2. Under the server's limits, in a fresh container (PowerShell):

       docker run --rm --cpus 0.1 --memory 512m --memory-swap 512m --network moneyangle_default `
         --env-file .env -e INDEX_PERF=1 -v "${PWD}\\backend:/app" moneyangle-backend `
         pytest transactions/test_index_performance.py -s -q -p no:cacheprovider
"""

import math
import os
import random
import statistics
import time
from decimal import Decimal

import pytest
from django.utils import timezone

from categories.models import Category
from categories.services import get_default_category
from datasources.services import first_source
from insights.management.commands.seed_demo_transactions import EVERYDAY, build_rows
from transactions import index
from transactions.index import Row, newest_first, rows_of
from transactions.models import CORE_CONTEXT, Transaction, decode_core
from transactions.tests import make_user
from vault.services import UserCipher, cipher_for

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.skipif(not os.environ.get("INDEX_PERF"), reason="set INDEX_PERF=1 to run"),
]

ROWS = 20_000
REPEATS = 5  # timed reads, after one warm-up
SERVER_CPUS = 0.1
BATCH = 1_000
ROWS_PER_SCALE = sum(spec[-1] for spec in EVERYDAY) * 12  # everyday rows in 12 months, scale 1


def _money(value: Decimal) -> bytes:
    return f"{value:.2f}".encode()


def _seed(user, count: int) -> None:
    """Fictional transactions, inserted in bulk with their real encryption contexts."""
    rng = random.Random(2026)
    rows = build_rows(timezone.localdate(), 12, math.ceil(count / ROWS_PER_SCALE), rng)[-count:]
    categories = {c.name.lower(): c for c in Category.objects.filter(user=user)}
    fallback = get_default_category(user)
    cipher = UserCipher(user)
    source = first_source(user)
    for start in range(0, len(rows), BATCH):
        txns = [
            Transaction(
                user=user,
                date=row["date"],
                txn_type=row["txn_type"],
                category=categories.get(row["category"].lower(), fallback),
                data_source=source,
                name_enc=cipher.encrypt(row["name"].encode(), "txn.name"),
                description_enc=cipher.encrypt(row["description"].encode(), "txn.description"),
                amount_enc=cipher.encrypt(_money(row["amount"]), "txn.amount"),
                balance_enc=cipher.encrypt(_money(row["balance"]), "txn.balance"),
                fingerprint=cipher.blind_index(f"perf|{start + i}".encode(), "txn.fp"),
            )
            for i, row in enumerate(rows[start : start + BATCH])
        ]
        for txn in txns:  # bulk_create skips save(), which encrypts the core
            txn.seal()
        Transaction.objects.bulk_create(txns)


def _cpu_limit() -> float | None:
    try:
        with open("/sys/fs/cgroup/cpu.max") as file:
            quota, period = file.read().split()
    except (OSError, ValueError):
        return None
    return None if quota == "max" else int(quota) / int(period)


def _timed(work) -> tuple[float, float, object]:
    """(wall ms, CPU ms, result) of one call."""
    wall, cpu = time.perf_counter(), time.process_time()
    result = work()
    return (time.perf_counter() - wall) * 1000, (time.process_time() - cpu) * 1000, result


def _on_server(wall: float, cpu: float, throttled: bool) -> float:
    """Milliseconds at 0.1 CPU: measured if throttled, else waiting plus CPU time stretched."""
    return wall if throttled else (wall - cpu) + cpu / SERVER_CPUS


def _parts(user) -> dict[str, tuple[float, float]]:
    """Each part of `rows_of` and the sort after it, timed on its own."""
    cipher = cipher_for(user.pk)
    parts = {}
    queryset = Transaction.objects.filter(user=user).order_by()
    wall, cpu, fetched = _timed(
        lambda: list(queryset.values_list("pk", "core_enc", "created_at").iterator(chunk_size=2000))
    )
    parts["fetch"] = (wall, cpu)
    wall, cpu, raw = _timed(lambda: [cipher.decrypt(blob, CORE_CONTEXT) for _, blob, _ in fetched])
    parts["decrypt"] = (wall, cpu)
    wall, cpu, cores = _timed(lambda: [decode_core(value) for value in raw])
    parts["parse"] = (wall, cpu)
    wall, cpu, rows = _timed(
        lambda: [Row(pk, *core, created) for (pk, _, created), core in zip(fetched, cores)]
    )
    parts["build rows"] = (wall, cpu)
    wall, cpu, _ = _timed(lambda: newest_first(rows))
    parts["sort"] = (wall, cpu)
    return parts


def test_reading_every_core_at_twenty_thousand_rows():
    cpus = _cpu_limit()
    throttled = cpus is not None and cpus <= SERVER_CPUS + 1e-9
    user = make_user("index-perf@example.com")
    _seed(user, ROWS)
    every = Transaction.objects.filter(user=user)
    rows_of(user)  # warm-up, and builds the index

    def one_by_one():
        return newest_first(index._decrypt_rows(user, every))

    def from_index():
        return newest_first(rows_of(user))

    def search_like():  # what a search reads: the newest 8k rows' ids
        return index.ids(from_index()[:8000])

    def every_row():  # the worst case: a caller that reads every Row
        return list(from_index())

    def rebuild():  # the first read after an import or an edit
        return index._rebuild_index(user)

    timings = {name: [] for name in ("one by one", "index", "index, 8k ids", "index, every Row",
                                     "rebuild")}  # fmt: skip
    parts = []
    for _ in range(REPEATS):
        for name, work in zip(timings, (one_by_one, from_index, search_like, every_row, rebuild)):
            wall, cpu, result = _timed(work)
            assert len(result) == (8000 if name == "index, 8k ids" else ROWS)
            timings[name].append((_on_server(wall, cpu, throttled), cpu))
        parts.append(_parts(user))
    assert list(from_index()) == list(one_by_one())  # same rows, same order

    print(f"\nCPU limit: {cpus or 'none'}; {ROWS} rows; median of {REPEATS} reads at 0.1 CPU:")
    for name, runs in timings.items():
        server = statistics.median(s for s, _ in runs)
        cpu = statistics.median(c for _, c in runs)
        print(f"  {name:<18} {server:8.0f} ms   (CPU {cpu:6.1f} ms)")
    print("  one by one, by part:")
    for name in parts[0]:
        server = statistics.median(_on_server(*p[name], throttled) for p in parts)
        cpu = statistics.median(p[name][1] for p in parts)
        print(f"    {name:<16} {server:8.0f} ms   (CPU {cpu:6.1f} ms)")

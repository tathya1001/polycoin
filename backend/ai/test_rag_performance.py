"""Opt-in speed check: is one ask cheap enough for Render's free tier (0.1 CPU, 512 MB)?

Seeds two fictional users with 5,000 and 20,000 encrypted documents (random 768-dim vectors,
narration-like text) and times the server's whole share of one ask: the search, stage by stage,
then the answer context (sources, summary, prompt). Seeding takes a while, so this is skipped
unless asked for.

1. A quick estimate with no limits. Each stage's CPU time is scaled to Render's 0.1 CPU:

       docker compose exec -e RAG_PERF=1 backend pytest ai/test_rag_performance.py -s

2. The gate numbers, under Render's limits, in a fresh container (PowerShell). Not the dev
   container: its runserver autoreloader would share the 0.1 CPU.

       docker run --rm --cpus 0.1 --memory 512m --memory-swap 512m --network polycoin_default `
         --env-file .env -e RAG_PERF=1 -v "${PWD}\backend:/app" polycoin-backend `
         pytest ai/test_rag_performance.py -s -q -p no:cacheprovider

The gates are asserted only in run 2. The local database answers faster than Neon does, so the
"sql" stage is a lower bound; check it on production with the timings in the ask log line.
"""

import math
import os
import random
import time
import tracemalloc
from decimal import Decimal

import numpy as np
import pytest
from django.db import connection
from django.utils import timezone

from ai import rag_fakes as fakes
from ai.models import RagDocument
from ai.rag import codec
from ai.rag.answer import build_answer
from ai.rag.index import DOC_CONTEXT, TEXT_CONTEXT
from ai.rag.profiles import TEXT_VERSION
from ai.rag.retriever import EncryptedHybridRetriever
from categories.models import Category
from categories.services import get_default_category
from insights.management.commands.seed_demo_transactions import EVERYDAY, build_rows
from transactions.models import Transaction
from transactions.tests import make_user
from vault.services import UserCipher

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.skipif(not os.environ.get("RAG_PERF"), reason="set RAG_PERF=1 to run"),
]

MODEL, DIGEST = "nomic-embed-text:latest", "sha256:perf"
USERS = (5_000, 20_000)  # documents seeded per fictional user
ASKS = 20  # timed searches per scenario, after one warm-up
NO_CAP = 1_000_000
# (the user's documents, RAG_MAX_DOCS, the p95 gate in ms)
SCENARIOS = [
    (5_000, NO_CAP, 1_500),
    (20_000, NO_CAP, 4_000),
    (20_000, 8_000, 1_500),  # the production default: about a second at 0.1 CPU
]
RENDER_CPUS = 0.1
BATCH = 1_000
ROWS_PER_SCALE = sum(spec[-1] for spec in EVERYDAY) * 12  # everyday rows in 12 months, scale 1


def _money(value: Decimal) -> bytes:
    return f"{value:.2f}".encode()


def _seed(user, count: int, rng: random.Random, np_rng: np.random.Generator) -> None:
    """Fictional transactions plus one encrypted RagDocument each.

    Bulk inserts instead of create_transaction() and store_vectors(), so seeding stays bearable
    at 0.1 CPU. The encryption contexts and payload format are the real ones.
    """
    scale = math.ceil(count / ROWS_PER_SCALE)
    rows = build_rows(timezone.localdate(), 12, scale, rng)[-count:]
    categories = {c.name.lower(): c for c in Category.objects.filter(user=user)}
    fallback = get_default_category(user)
    cipher = UserCipher(user)

    for start in range(0, len(rows), BATCH):
        txns = Transaction.objects.bulk_create(
            [
                Transaction(
                    user=user,
                    date=row["date"],
                    txn_type=row["txn_type"],
                    category=categories.get(row["category"].lower(), fallback),
                    name_enc=cipher.encrypt(row["name"].encode(), "txn.name"),
                    description_enc=cipher.encrypt(row["description"].encode(), "txn.description"),
                    amount_enc=cipher.encrypt(_money(row["amount"]), "txn.amount"),
                    balance_enc=cipher.encrypt(_money(row["balance"]), "txn.balance"),
                    fingerprint=cipher.blind_index(f"perf|{start + i}".encode(), "txn.fp"),
                )
                for i, row in enumerate(rows[start : start + BATCH])
            ]
        )
        docs = []
        for txn, vector in zip(txns, fakes.unit_vectors(np_rng, len(txns))):
            text = fakes.fake_text(rng)
            docs.append(
                RagDocument(
                    user=user,
                    transaction=txn,
                    model=MODEL,
                    model_digest=DIGEST,
                    dims=fakes.DIMS,
                    text_version=TEXT_VERSION,
                    payload_enc=cipher.encrypt(codec.pack(vector, text), DOC_CONTEXT),
                    text_hash=cipher.blind_index(text.encode(), TEXT_CONTEXT),
                    source_updated_at=txn.updated_at,
                )
            )
        RagDocument.objects.bulk_create(docs)


def _search(user, rng, np_rng) -> dict:
    """One ask's server work, timed as a whole, by the retriever's stages, and the answer."""
    question = fakes.fake_question(rng)
    found = EncryptedHybridRetriever(
        user=user,
        model=MODEL,
        digest=DIGEST,
        query_vector=fakes.unit_vectors(np_rng, 1)[0].astype(float).tolist(),
    )
    wall, cpu = time.perf_counter(), time.process_time()
    result = found.search(question)
    search_wall, search_cpu = time.perf_counter(), time.process_time()
    context = build_answer(user, question, result, timezone.localdate())
    end_wall, end_cpu = time.perf_counter(), time.process_time()
    assert context["messages"]  # an untuned model always keeps its best vector match

    ms, cpu_ms = dict(result.stats["ms"]), dict(result.stats["cpu_ms"])
    ms["other"] = max((search_wall - wall) * 1000 - sum(ms.values()), 0.0)  # key, period, setup
    cpu_ms["other"] = max((search_cpu - cpu) * 1000 - sum(cpu_ms.values()), 0.0)
    ms["answer"] = (end_wall - search_wall) * 1000
    cpu_ms["answer"] = (end_cpu - search_cpu) * 1000
    return {
        "ms": ms,
        "cpu_ms": cpu_ms,
        "wall": (end_wall - wall) * 1000,
        "cpu": (end_cpu - cpu) * 1000,
    }


# --- Reporting ---------------------------------------------------------------------------------


def _cgroup(name: str) -> str | None:
    try:
        with open(f"/sys/fs/cgroup/{name}") as file:
            return file.read().strip()
    except OSError:
        return None


def _cpu_limit() -> float | None:
    """The container's CPU quota (0.1 under `docker run --cpus 0.1`), or None for no limit."""
    value = _cgroup("cpu.max")  # "10000 100000", or "max 100000"
    if not value or value.startswith("max"):
        return None
    quota, period = value.split()
    return int(quota) / int(period)


def _proc_mb(field: str) -> float:
    with open("/proc/self/status") as file:
        for line in file:
            if line.startswith(field + ":"):
                return int(line.split()[1]) / 1024
    return 0.0


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    middle = len(ordered) // 2
    return ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2


def _p95(values: list[float]) -> float:
    return sorted(values)[math.ceil(0.95 * len(values)) - 1]


def _render_ms(runs: list[dict], throttled: bool) -> list[float]:
    """Each search's total as Render would see it.

    Throttled: the measured wall time. Not throttled: waiting (wall minus CPU, mostly the
    database) is unchanged, and the CPU part takes 1 / 0.1 = 10 times longer.
    """
    if throttled:
        return [run["wall"] for run in runs]
    stretch = 1 / RENDER_CPUS - 1
    return [run["wall"] + run["cpu"] * stretch for run in runs]


def _report(title: str, runs: list[dict], throttled: bool, gate: int) -> float:
    print(f"\n{title}, {len(runs)} searches")
    print(f"  {'stage':<8} {'wall p50 ms':>12} {'cpu p50 ms':>11}")
    for stage in runs[0]["ms"]:
        wall = _median([run["ms"][stage] for run in runs])
        cpu = _median([run["cpu_ms"][stage] for run in runs])
        print(f"  {stage:<8} {wall:>12.1f} {cpu:>11.1f}")
    totals = _render_ms(runs, throttled)
    p95 = _p95(totals)
    label = "measured at 0.1 CPU" if throttled else "ESTIMATED for 0.1 CPU"
    print(
        f"  total ({label}): p50 {_median(totals):,.0f} ms, p95 {p95:,.0f} ms, "
        f"max {max(totals):,.0f} ms -> gate p95 <= {gate:,} ms: "
        f"{'PASS' if p95 <= gate else 'FAIL'}"
    )
    return p95


def test_one_search_at_five_and_twenty_thousand_documents(settings):
    cpus = _cpu_limit()
    throttled = cpus is not None and cpus <= RENDER_CPUS + 1e-9
    print(f"\nCPU limit: {cpus or 'none'}, memory limit: {_cgroup('memory.max') or 'unknown'}")
    rng, np_rng = random.Random(1), np.random.default_rng(1)

    users = {}
    for size in USERS:
        users[size] = make_user(f"rag-perf-{size}@example.com")
        started = time.perf_counter()
        _seed(users[size], size, rng, np_rng)
        print(f"Seeded {size:,} documents in {time.perf_counter() - started:.1f} s")

    table = RagDocument._meta.db_table
    with connection.cursor() as cursor:
        # Production's autovacuum analyzes a table after big changes such as an import. The test
        # rows sit in one uncommitted transaction it can't see, so without this Postgres plans
        # for empty tables and picks a nested-loop join that scans the documents per row.
        cursor.execute(f"ANALYZE {table}, {Transaction._meta.db_table}, {Category._meta.db_table}")
        cursor.execute(
            f"SELECT count(*), avg(octet_length(payload_enc)), pg_total_relation_size('{table}') "
            f"FROM {table}"
        )
        count, payload_bytes, table_bytes = cursor.fetchone()
    assert count == sum(USERS)
    print(
        f"Storage: {float(payload_bytes):,.0f} bytes per encrypted payload; "
        f"table + indexes {table_bytes / count * 5_000 / 1e6:.1f} MB per 5,000 documents; "
        f"one search over 5,000 reads about {float(payload_bytes) * 5_000 / 1e6:.1f} MB"
    )

    failures = []
    for size, max_docs, gate in SCENARIOS:
        settings.RAG_MAX_DOCS = max_docs
        _search(users[size], rng, np_rng)  # warm-up
        runs = [_search(users[size], rng, np_rng) for _ in range(ASKS)]
        capped = f", newest {max_docs:,} searched" if max_docs < size else ""
        title = f"{size:,} documents{capped}"
        p95 = _report(title, runs, throttled, gate)
        if p95 > gate:
            failures.append(f"{title}: p95 {p95:,.0f} ms > {gate:,} ms")

    # Python + numpy allocations of one uncapped 20k search (tracemalloc slows it, so it isn't
    # timed). ai/rag_memory.py measures the real resident memory in the production image.
    settings.RAG_MAX_DOCS = NO_CAP
    tracemalloc.start()
    _search(users[20_000], rng, np_rng)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    print(
        f"\nPeak allocations during one 20,000-document search: {peak / 2**20:.0f} MB "
        f"(this pytest process: RSS {_proc_mb('VmRSS'):.0f} MB, peak {_proc_mb('VmHWM'):.0f} MB)"
    )

    if not throttled:
        print("Not limited to 0.1 CPU, so the gates are reported, not asserted (see run 2).")
        return
    assert not failures, failures

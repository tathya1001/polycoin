"""Opt-in cost check: is the AI panel builder cheap enough for Render's free tier (0.1 CPU,
512 MB)? It needs no model: the replies a correct model gives are relayed instead.

Measured, each against its gate:
- the builder's own server time per request (a turn or a step), merchant lookups aside:
  p95 <= 500 ms. A step that ends in a preview also runs the panel's query, which costs what the
  same panel costs on the dashboard; it is reported on its own and has no gate here;
- the merchant scan of AGENT_MERCHANT_SCAN (5,000) encrypted names: <= 1,000 ms;
- the sealed token: p95 <= 8 KB;
- what loading the builder adds to a worker on top of "Ask": <= 4 s and <= 30 MB.

1. A quick estimate with no limits; CPU time is scaled to Render's 0.1 CPU:

       docker compose exec -e AGENT_PERF=1 backend pytest ai/test_agent_performance.py -s

2. The gate numbers, under Render's limits, in a fresh container (PowerShell):

       docker run --rm --cpus 0.1 --memory 512m --memory-swap 512m --network polycoin_default `
         --env-file .env -e AGENT_PERF=1 -v "${PWD}\backend:/app" polycoin-backend `
         pytest ai/test_agent_performance.py -s -q -p no:cacheprovider

The gates are asserted only in run 2.
"""

import json
import math
import os
import random
import subprocess
import sys
import time
from decimal import Decimal

import pytest
from django.utils import timezone

from ai.agent import compile as compiler
from ai.agent import service
from ai.agent.context import merchant_names
from ai.test_rag_performance import RENDER_CPUS, _cgroup, _cpu_limit, _median, _p95
from categories.models import Category
from categories.services import get_default_category
from insights.management.commands.seed_demo_transactions import EVERYDAY, build_rows
from transactions.models import Transaction
from transactions.tests import make_user
from vault.services import UserCipher

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.skipif(not os.environ.get("AGENT_PERF"), reason="set AGENT_PERF=1 to run"),
]

ROWS = 5_000
BATCH = 1_000
REPEATS = 5  # conversations per script, after one warm-up
STEP_GATE_MS, SCAN_GATE_MS, TOKEN_GATE, IMPORT_GATE_S, MEMORY_GATE_MB = 500, 1_000, 8_192, 4.0, 30
ROWS_PER_SCALE = sum(spec[-1] for spec in EVERYDAY) * 12  # everyday rows in 12 months, scale 1


def _reply(**fields) -> str:
    return json.dumps({"kind": "panel", **fields})


# Conversations as (message, the reply a correct model gives). Each list is one conversation.
SCRIPTS = [
    [("spend by category", _reply(chart="bar", measure="spend", x="category"))],
    [
        (
            "monthly spend this year",
            _reply(chart="line", measure="spend", x="date", period="this_year"),
        ),
        (
            "make it weekly",
            _reply(chart="line", measure="spend", x="date", granularity="week", period="this_year"),
        ),  # fmt: skip
        (
            "as bars",
            _reply(chart="bar", measure="spend", x="date", granularity="week", period="this_year"),
        ),
    ],
    [
        (
            "total spend compared with last month",
            _reply(chart="kpi", measure="spend", compare="previous"),
        )
    ],
]
MERCHANT = ("spend at the cafe", _reply(chart="kpi", measure="spend", merchant="cafe"))


def _money(value: Decimal) -> bytes:
    return f"{value:.2f}".encode()


def _seed(user, count: int) -> None:
    """Fictional transactions over 12 months, bulk-inserted with the real encryption contexts."""
    scale = math.ceil(count / ROWS_PER_SCALE)
    rows = build_rows(timezone.localdate(), 12, scale, random.Random(3))[-count:]
    categories = {c.name.lower(): c for c in Category.objects.filter(user=user)}
    fallback = get_default_category(user)
    cipher = UserCipher(user)
    for start in range(0, len(rows), BATCH):
        Transaction.objects.bulk_create(
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
                    fingerprint=cipher.blind_index(f"agent-perf|{start + i}".encode(), "txn.fp"),
                )
                for i, row in enumerate(rows[start : start + BATCH])
            ]
        )


def _timed(call) -> tuple[dict, float, float]:
    wall, cpu = time.perf_counter(), time.process_time()
    result = call()
    return result, (time.perf_counter() - wall) * 1000, (time.process_time() - cpu) * 1000


def _render_ms(wall: float, cpu: float, throttled: bool) -> float:
    """As Render would see it: measured when throttled, else the CPU part stretched 10 times."""
    return wall if throttled else wall + cpu * (1 / RENDER_CPUS - 1)


class PreviewClock:
    """Time spent in the preview's panel query, so it can be told apart from the builder's own."""

    def __init__(self, real):
        self.real, self.wall, self.cpu = real, 0.0, 0.0

    def __call__(self, *args, **kwargs):
        result, wall, cpu = _timed(lambda: self.real(*args, **kwargs))
        self.wall += wall
        self.cpu += cpu
        return result


def _request(call, clock: PreviewClock, throttled: bool) -> tuple[dict, float, float]:
    """(response, the builder's own Render ms, the preview query's Render ms)."""
    wall_before, cpu_before = clock.wall, clock.cpu
    response, wall, cpu = _timed(call)
    preview_wall, preview_cpu = clock.wall - wall_before, clock.cpu - cpu_before
    own = _render_ms(wall - preview_wall, cpu - preview_cpu, throttled)
    return response, own, _render_ms(preview_wall, preview_cpu, throttled)


def _converse(user, script, clock: PreviewClock, throttled: bool):
    """One conversation: ([(builder ms, preview query ms)] per request, token sizes). A turn
    runs no preview query, so its second number is 0."""
    requests, tokens, token = [], [], None
    for message, reply in script:
        response, own, query = _request(
            lambda: service.turn(user, message, token, {}, None), clock, throttled
        )
        requests.append((own, query))
        while response["status"] == "needs_model":
            current = response["token"]
            response, own, query = _request(
                lambda: service.step(user, current, reply=reply), clock, throttled
            )
            requests.append((own, query))
        assert response["outcome"]["kind"] == "preview", response["outcome"]
        token = response["token"]
        tokens.append(len(token))
    return requests, tokens


_CHILD = """
import os, sys, time, resource
sys.path.insert(0, "/app")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django
django.setup()
import ai.rag_views
start, wall = resource.getrusage(resource.RUSAGE_SELF), time.perf_counter()
rss = [int(l.split()[1]) for l in open("/proc/self/status") if l.startswith("VmRSS:")][0]
if sys.argv[1] == "agent":
    import ai.agent_views
end, wall = resource.getrusage(resource.RUSAGE_SELF), time.perf_counter() - wall
after = [int(l.split()[1]) for l in open("/proc/self/status") if l.startswith("VmRSS:")][0]
cpu = (end.ru_utime + end.ru_stime) - (start.ru_utime + start.ru_stime)
print(cpu, wall, (after - rss) / 1024)
"""


def _import_cost(throttled: bool) -> tuple[float, float]:
    """(seconds, MB) that loading the builder adds to a worker that already serves "Ask".
    Throttled: the measured wall time. Otherwise: the CPU time, stretched to 0.1 CPU."""
    output = subprocess.run(
        [sys.executable, "-c", _CHILD, "agent"], capture_output=True, text=True, check=True
    ).stdout.split()
    cpu, wall, mb = (float(value) for value in output)
    return (wall if throttled else cpu / RENDER_CPUS), mb


def test_the_panel_builder_fits_the_free_tier(settings, monkeypatch):
    cpus = _cpu_limit()
    throttled = cpus is not None and cpus <= RENDER_CPUS + 1e-9
    label = "measured at 0.1 CPU" if throttled else "ESTIMATED for 0.1 CPU"
    print(f"\nCPU limit: {cpus or 'none'}, memory limit: {_cgroup('memory.max') or 'unknown'}")

    user = make_user("agent-perf@example.com")
    started = time.perf_counter()
    _seed(user, ROWS)
    print(f"Seeded {ROWS:,} transactions in {time.perf_counter() - started:.1f} s")

    clock = PreviewClock(compiler.run_queries)
    monkeypatch.setattr(compiler, "run_queries", clock)
    for script in SCRIPTS:  # warm-up: imports, first queries
        _converse(user, script, clock, throttled)
    requests, tokens = [], []
    for _ in range(REPEATS):
        for script in SCRIPTS:
            more_requests, more_tokens = _converse(user, script, clock, throttled)
            requests += more_requests
            tokens += more_tokens
    times = [own for own, _ in requests]
    queries = [query for _, query in requests if query]  # the steps that drew a preview
    whole = [own + query for own, query in requests]

    names, wall, cpu = _timed(lambda: merchant_names(user, settings.AGENT_MERCHANT_SCAN))
    scan = _render_ms(wall, cpu, throttled)
    merchant_requests, _ = _converse(user, [MERCHANT], clock, throttled)
    merchant_times = [own + query for own, query in merchant_requests]
    seconds, mb = _import_cost(throttled)

    failures = []

    def gate(name: str, value: float, limit: float, unit: str) -> None:
        ok = value <= limit
        print(
            f"  {name:<34} {value:>9,.1f} {unit:<3} gate <= {limit:,} {unit}: {'PASS' if ok else 'FAIL'}"
        )
        if not ok:
            failures.append(name)

    print(f"\nPanel builder, {len(times)} requests over {ROWS:,} transactions ({label})")
    print(f"  builder's own time p50 {_median(times):,.0f} ms, max {max(times):,.0f} ms")
    gate("builder's own time p95", _p95(times), STEP_GATE_MS, "ms")
    print(
        f"  preview query (the dashboard's cost for the same panel): p50 {_median(queries):,.0f} ms,"
        f" p95 {_p95(queries):,.0f} ms; whole requests with it: p95 {_p95(whole):,.0f} ms"
    )
    gate(f"merchant scan ({len(names):,} distinct names)", scan, SCAN_GATE_MS, "ms")
    print(f"  a request with a merchant lookup: max {max(merchant_times):,.0f} ms")
    gate("token p95", _p95(tokens), TOKEN_GATE, "B")
    gate("import on top of Ask", seconds, IMPORT_GATE_S, "s")
    gate("memory on top of Ask", mb, MEMORY_GATE_MB, "MB")

    if throttled:
        assert not failures, failures

"""Opt-in cost check: can Render's free tier (0.1 CPU, 512 MB) make and restore a backup of
20,000 transactions inside the Vercel proxy's 30-second limit, and does the file fit the upload
cap? Seeding takes a while, so this is skipped unless asked for.

1. A quick estimate with no limits; CPU time is scaled to Render's 0.1 CPU:

       docker compose exec -e BACKUP_PERF=1 backend pytest backups/test_performance.py -s

2. The gate numbers, under Render's limits, in a fresh container (PowerShell):

       docker run --rm --cpus 0.1 --memory 512m --memory-swap 512m --network polycoin_default `
         --env-file .env -e BACKUP_PERF=1 -v "${PWD}\\backend:/app" polycoin-backend `
         pytest backups/test_performance.py -s -q -p no:cacheprovider

The gates are asserted only in run 2.
"""

import os
import resource
import time

import pytest
from django.conf import settings

from accounts.services import delete_user_data
from ai.test_agent_performance import _render_ms, _seed, _timed
from ai.test_rag_performance import RENDER_CPUS, _cgroup, _cpu_limit
from backups.services import build_backup, restore_backup
from transactions.models import Transaction
from transactions.tests import make_user

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.skipif(not os.environ.get("BACKUP_PERF"), reason="set BACKUP_PERF=1 to run"),
]

ROWS = 20_000
TIME_GATE_MS = 20_000  # each way; the proxy cuts a request at 30 s
MEMORY_GATE_MB = 350  # peak of the whole process, under the 512 MB container


def _peak_mb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024  # Linux reports kB


def test_a_backup_of_twenty_thousand_rows_fits_the_free_tier():
    cpus = _cpu_limit()
    throttled = cpus is not None and cpus <= RENDER_CPUS + 1e-9
    label = "measured at 0.1 CPU" if throttled else "ESTIMATED for 0.1 CPU"
    print(f"\nCPU limit: {cpus or 'none'}, memory limit: {_cgroup('memory.max') or 'unknown'}")

    user = make_user("backup-perf@example.com")
    started = time.perf_counter()
    _seed(user, ROWS)
    print(f"Seeded {ROWS:,} transactions in {time.perf_counter() - started:.1f} s")

    content, wall, cpu = _timed(lambda: build_backup(user))
    make_ms = _render_ms(wall, cpu, throttled)
    delete_user_data(user)
    counts, wall, cpu = _timed(lambda: restore_backup(user, content))
    restore_ms = _render_ms(wall, cpu, throttled)
    assert counts["transactions"]["added"] == ROWS == Transaction.objects.filter(user=user).count()

    per_row = len(content) / ROWS
    fits = int(settings.BACKUP_MAX_BYTES / per_row)
    peak = _peak_mb()
    failures = []

    def gate(name: str, value: float, limit: float, unit: str) -> None:
        ok = value <= limit
        print(
            f"  {name:<28} {value:>10,.0f} {unit:<3} gate <= {limit:,} {unit}: {'PASS' if ok else 'FAIL'}"
        )
        if not ok:
            failures.append(name)

    print(f"\nData Backup File, {ROWS:,} transactions ({label})")
    gate("make the file", make_ms, TIME_GATE_MS, "ms")
    gate("restore it", restore_ms, TIME_GATE_MS, "ms")
    gate("file size", len(content) / 1024, settings.BACKUP_MAX_BYTES / 1024, "KB")
    gate("peak memory (process)", peak, MEMORY_GATE_MB, "MB")
    print(f"  {per_row:.0f} bytes per transaction: about {fits:,} transactions fit the upload cap")

    if throttled:
        assert not failures, failures

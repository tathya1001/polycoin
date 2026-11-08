"""Opt-in speed check: preparing a categorisation run at 5,000 and 20,000 transactions.

prepare_run decrypts every row's core to find the uncategorised ones and the user's examples, so
its cost grows with the account. Reported, not gated. Run it like ai/test_rag_performance.py: the
numbers that count come from a container limited to 0.1 CPU and 512 MB.

    docker compose exec -e RAG_PERF=1 backend pytest ai/test_categorize_performance.py -s
"""

import math
import os
import random
import statistics
import time

import numpy as np
import pytest
from django.conf import settings

from ai import services
from ai.test_rag_performance import _cpu_limit, _seed
from categories.services import get_default_category
from transactions.models import Transaction
from transactions.tests import make_user

pytestmark = pytest.mark.django_db
RUNS = 5  # timed runs per size, after one warm-up


@pytest.mark.skipif(not os.environ.get("RAG_PERF"), reason="set RAG_PERF=1 to run")
def test_prepare_run_at_five_and_twenty_thousand_rows():
    print(f"\nCPU limit: {_cpu_limit() or 'none'}")
    rng, np_rng = random.Random(2), np.random.default_rng(2)
    for size in (5_000, 20_000):
        user = make_user(f"categorize-perf-{size}@example.com")
        _seed(user, size, rng, np_rng)
        # The seeded rows all have a category; a run needs uncategorised rows to work on.
        default = get_default_category(user)
        for txn in Transaction.objects.filter(user=user)[: settings.AI_MAX_RUN]:
            txn.category = default
            txn.save()
        services.prepare_run(user)  # warm-up
        times = []
        for _ in range(RUNS):
            started = time.perf_counter()
            run = services.prepare_run(user)
            times.append((time.perf_counter() - started) * 1000)
        ordered = sorted(times)
        print(
            f"{size:,} rows: prepare_run p50 {statistics.median(times):,.0f} ms, max "
            f"{ordered[-1]:,.0f} ms ({run['considered']} rows to categorise, "
            f"{len(run['texts'])} texts)"
        )
        assert run["texts"] and not math.isnan(ordered[-1])

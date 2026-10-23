"""Opt-in timing check: 20,000 rows, one 12-panel batch, within about 2 s.

Seeding 20,000 encrypted rows takes a while, so this is skipped unless asked for:

    docker compose exec -e INSIGHTS_PERF=1 backend pytest insights/test_performance.py -s

The measured time is printed; it decides whether INSIGHTS_MAX_ROWS (50,000) needs to change.
"""

import os
import time

import pytest
from django.core.management import call_command
from django.utils import timezone

from insights import services
from insights.templates import TEMPLATES
from transactions.models import Transaction
from transactions.tests import make_user

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.skipif(not os.environ.get("INSIGHTS_PERF"), reason="set INSIGHTS_PERF=1 to run"),
]

TARGET_ROWS = 20_000
BUDGET_SECONDS = 2.0

# Twelve panels: the seven from Overview plus five that need the merchant name and balance,
# so the batch decrypts every optional field, the worst case.
EXTRA = [
    {"chart": "bar", "x": {"field": "merchant"}, "y": {"measure": "spend"}},
    {"chart": "line", "x": {"field": "date", "granularity": "week"}, "y": {"measure": "balance"}},
    {"chart": "bar", "x": {"field": "weekday"}, "y": {"measure": "spend", "agg": "avg"}},
    {"chart": "kpi", "y": {"measure": "count"}, "filters": {"merchant_contains": "cafe"}},
    {"chart": "line", "x": {"field": "date", "granularity": "day"}, "y": {"measure": "net"}},
]


def test_a_twelve_panel_batch_over_twenty_thousand_rows(settings):
    settings.DEBUG = True
    user = make_user("perf@example.com")
    call_command("seed_demo_transactions", user=user.email, months=12, scale=55, seed=1)
    assert Transaction.objects.filter(user=user).count() >= TARGET_ROWS

    specs = [panel["config"] for panel in TEMPLATES["overview"]] + EXTRA
    queries = [{"key": str(index), "spec": spec} for index, spec in enumerate(specs)]
    filters = {"date": {"preset": "last_12_months"}}

    started = time.perf_counter()
    results = services.run_queries(user, filters, queries, today=timezone.localdate())
    elapsed = time.perf_counter() - started

    print(f"\n{len(queries)} panels over {Transaction.objects.count()} rows: {elapsed:.2f} s")
    assert all("error" not in result for result in results.values())
    assert elapsed < BUDGET_SECONDS

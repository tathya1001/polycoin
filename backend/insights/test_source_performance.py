"""Opt-in timing check for data sources: 20,000 rows split across five sources.

Skipped unless asked for, like test_performance.py, and run the same way:

    docker compose exec -e INSIGHTS_PERF=1 backend pytest insights/test_source_performance.py -s

Gates: a formula that names sources stays under 2x the same panels with plain measures, a batch
reading balances fits the normal budget, and finding transfers over a year takes under 3 s.
"""

import os
import resource
import time

import pytest
from django.core.management import call_command
from django.utils import timezone

from datasources.services import create_source, first_source
from insights import services
from insights.test_performance import BUDGET_SECONDS, THROTTLED_BUDGET_SECONDS, _cpu_limit
from transactions.links import suggest_transfers
from transactions.models import Transaction, TransferLink
from transactions.tests import make_user
from vault.services import UserCipher

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.skipif(not os.environ.get("INSIGHTS_PERF"), reason="set INSIGHTS_PERF=1 to run"),
]

SOURCES = 5
LINKS = 100
MAX_NAMED_SLOWDOWN = 2.0
SUGGESTIONS_SECONDS = 3.0
MONTHLY = {"field": "date", "granularity": "month"}
WEEKLY = {"field": "date", "granularity": "week"}
PLAIN = [
    {"chart": "kpi", "y": {"measure": "spend"}},
    {"chart": "bar", "x": MONTHLY, "y": {"measure": "income"}},
    {"chart": "line", "x": WEEKLY, "y": {"measure": "net"}},
    {"chart": "bar", "x": {"field": "category"}, "y": {"measure": "spend"}},
]


def named(chart: dict, text: str) -> dict:
    formula = {"expression": text, "as": "money"}
    return {**chart, "y": {"measure": "formula", "formula": formula}}


def split_into_sources(user) -> None:
    """Spreads the seeded rows over the sources evenly, and links a few as transfers."""
    cipher = UserCipher(user)
    sources = [first_source(user)]
    sources += [create_source(user, cipher, f"Source {n}") for n in range(1, SOURCES)]
    ids = list(Transaction.objects.filter(user=user).order_by("pk").values_list("pk", flat=True))
    for index, source in enumerate(sources):
        Transaction.objects.filter(pk__in=ids[index::SOURCES]).update(data_source=source)

    debits = Transaction.objects.filter(data_source=sources[0], txn_type="debit")[:LINKS]
    credits = Transaction.objects.filter(data_source=sources[1], txn_type="credit")[:LINKS]
    TransferLink.objects.bulk_create(
        TransferLink(user=user, debit=debit, credit=credit)
        for debit, credit in zip(debits, credits, strict=False)
    )


def timed(run) -> tuple:
    started = time.perf_counter()
    result = run()
    return result, time.perf_counter() - started


def test_data_sources_over_twenty_thousand_rows(settings):
    settings.DEBUG = True
    user = make_user("perf@example.com")
    call_command("seed_demo_transactions", user=user.email, months=12, scale=55, seed=1)
    settings.DEBUG = False  # DEBUG keeps every query in memory, which production never does
    split_into_sources(user)
    today = timezone.localdate()
    filters = {"date": {"preset": "last_12_months"}}

    def batch(specs: list[dict]) -> dict:
        queries = [{"key": str(index), "spec": spec} for index, spec in enumerate(specs)]
        return services.run_queries(user, filters, queries, today=today)

    plain, plain_elapsed = timed(lambda: batch(PLAIN))
    print(f"\n{len(PLAIN)} panels with links on: {plain_elapsed:.2f} s")
    assert all("error" not in result for result in plain.values())

    text = "Main.spend - [Source 1].income + [Source 2].net"
    with_names = [named(spec, text) if spec["chart"] != "pie" else spec for spec in PLAIN]
    names, names_elapsed = timed(lambda: batch(with_names))
    print(f"the same panels naming sources: {names_elapsed:.2f} s")
    assert all("error" not in result for result in names.values())

    balances = [
        {"chart": "kpi", "y": {"measure": "balance"}},
        {"chart": "line", "x": WEEKLY, "y": {"measure": "balance"}},
        {
            "chart": "line",
            "x": MONTHLY,
            "color": {"field": "data_source"},
            "y": {"measure": "balance"},
        },
        {"chart": "bar", "x": {"field": "data_source"}, "y": {"measure": "balance"}},
    ]
    held, balances_elapsed = timed(lambda: batch(balances))
    print(f"{len(balances)} balance panels: {balances_elapsed:.2f} s")
    assert all("error" not in result for result in held.values())

    five = {
        "chart": "line",
        "x": WEEKLY,
        "y": {"measure": "spend"},
        "also": [
            {"measure": "income"},
            {"measure": "balance"},
            named({}, "Main.spend")["y"],
            named({}, 'SUM(IF [Category] = "Food" THEN [Spend] END) / spend * 100')["y"],
        ],
    }
    measured, measured_elapsed = timed(lambda: batch([five]))
    print(f"one chart of five measures: {measured_elapsed:.2f} s")
    assert all("error" not in result for result in measured.values())

    start = today.replace(year=today.year - 1)
    found, found_elapsed = timed(
        lambda: suggest_transfers(user, UserCipher(user), start, today)
    )
    print(f"finding transfers ({found['total']} pairs): {found_elapsed:.2f} s")
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024
    print(f"peak memory of this test process: {peak} MB")

    limit = _cpu_limit()
    throttled = limit is not None and limit <= 0.1
    assert names_elapsed < plain_elapsed * MAX_NAMED_SLOWDOWN
    budget = THROTTLED_BUDGET_SECONDS if throttled else BUDGET_SECONDS
    assert balances_elapsed < budget
    assert measured_elapsed < budget
    if not throttled:
        assert found_elapsed < SUGGESTIONS_SECONDS

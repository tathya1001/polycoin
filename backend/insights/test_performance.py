"""Opt-in timing check: 20,000 rows, one 12-panel batch.

Seeding 20,000 encrypted rows takes a while, so this is skipped unless asked for:

    docker compose exec -e INSIGHTS_PERF=1 backend pytest insights/test_performance.py -s

Gates: the batch takes under 2 s on a normal CPU and under 12 s at Render's 0.1 CPU (measured:
0.5 s and 7 s), and neither table calculations, calculated fields nor a click selection make it
more than 1.5x slower. Listing the transactions behind one mark must fit the same budget. Run it at Render's
limits with (PowerShell):

    docker run --rm --cpus 0.1 --memory 512m --memory-swap 512m --network polycoin_default `
      --env-file .env -e INSIGHTS_PERF=1 -v "${PWD}/backend:/app" polycoin-backend `
      pytest insights/test_performance.py -s -q -p no:cacheprovider

The measured times are printed; they decide whether INSIGHTS_MAX_ROWS needs to change.
"""

import os
import time
from pathlib import Path

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


def _cpu_limit() -> float | None:
    """The container's CPU quota (0.1 under `docker run --cpus 0.1`), or None for no limit."""
    try:
        value = Path("/sys/fs/cgroup/cpu.max").read_text().split()
    except OSError:
        return None
    return None if value[0] == "max" else int(value[0]) / int(value[1])


BUDGET_SECONDS = 2.0  # on a normal CPU
THROTTLED_BUDGET_SECONDS = 12.0  # in a container limited to Render's 0.1 CPU
MAX_CALC_SLOWDOWN = 1.5  # table calculations vs the same batch without them
MAX_SELECTION_SLOWDOWN = 1.5  # a click selection vs the same batch without it
MAX_FORMULA_SLOWDOWN = 1.5  # calculated fields vs the same panels with plain measures
FORMULA = {
    "measure": "formula",
    "formula": {"expression": "(income - spend) / max(income, 1) * 100", "as": "percent"},
}

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

    # The same batch with table calculations on the panels that can take one, to price them.
    with_calcs = [
        {**query, "spec": {**query["spec"], **_calc_for(query["spec"])}} for query in queries
    ]
    started = time.perf_counter()
    calc_results = services.run_queries(user, filters, with_calcs, today=timezone.localdate())
    calc_elapsed = time.perf_counter() - started
    calculated = sum("calc" in query["spec"] for query in with_calcs)
    print(f"the same batch with {calculated} table calculations: {calc_elapsed:.2f} s")
    assert all("error" not in result for result in calc_results.values())

    # The same batch with a click on the first panel narrowing the other eleven.
    picked = {"categories": ["Food"], "weekdays": [0, 1, 2, 3]}
    started = time.perf_counter()
    selected = services.run_queries(
        user, filters, queries, today=timezone.localdate(), selection=picked, selection_source="0"
    )
    selection_elapsed = time.perf_counter() - started
    print(f"the same batch with a selection: {selection_elapsed:.2f} s")
    assert all("error" not in result for result in selected.values())

    # The same batch with a calculated field on every panel that can take one.
    with_formulas = [{**query, "spec": _formula_for(query["spec"])} for query in queries]
    started = time.perf_counter()
    formula_results = services.run_queries(
        user, filters, with_formulas, today=timezone.localdate()
    )
    formula_elapsed = time.perf_counter() - started
    formulas = sum(query["spec"]["y"]["measure"] == "formula" for query in with_formulas)
    print(f"the same batch with {formulas} calculated fields: {formula_elapsed:.2f} s")
    assert all("error" not in result for result in formula_results.values())

    # The transactions behind one bar.
    started = time.perf_counter()
    listing = services.list_rows(user, filters, specs[0], {"categories": ["Food"]})
    rows_elapsed = time.perf_counter() - started
    print(f"the transactions behind one bar ({listing['total']} rows): {rows_elapsed:.2f} s")

    limit = _cpu_limit()
    budget = THROTTLED_BUDGET_SECONDS if limit is not None and limit <= 0.1 else BUDGET_SECONDS
    assert elapsed < budget
    assert calc_elapsed < elapsed * MAX_CALC_SLOWDOWN
    assert selection_elapsed < elapsed * MAX_SELECTION_SLOWDOWN
    assert formula_elapsed < elapsed * MAX_FORMULA_SLOWDOWN
    assert rows_elapsed < budget


def _formula_for(spec: dict) -> dict:
    """The panel with a calculated field instead of its measure, where it can take one."""
    if spec["chart"] not in ("bar", "line", "area", "kpi"):
        return spec
    changed = {**spec, "y": FORMULA}
    if spec["chart"] == "kpi":
        # The money figures under a KPI need a money measure; the count still works.
        kpi = dict(spec.get("kpi") or {})
        kpi["secondary"] = [f for f in kpi.get("secondary", []) if f == "count"]
        changed["kpi"] = kpi
    return changed


def _calc_for(spec: dict) -> dict:
    """A table calculation this panel can take: the costliest kind that fits."""
    if spec["chart"] not in ("bar", "line", "area"):
        return {}
    if spec.get("x", {}).get("field") == "date":
        return {"calc": {"type": "change", "vs": "year_ago"}}  # loads a second year of rows
    if spec["y"].get("agg", "sum") == "sum" and spec["y"]["measure"] not in ("net", "balance"):
        return {"calc": {"type": "percent_of_total"}}
    return {}

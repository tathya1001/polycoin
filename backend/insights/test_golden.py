"""Characterisation test: saved panel configs must keep producing exactly the same chart data.

Panels saved by older versions of the spec live in production. Each case here is such a config,
run on fixed fictional rows; the outputs recorded in golden/engine_outputs.json were produced
before the spec gained versions beyond 1. A change that alters any of them fails here.

To record new outputs on purpose (only when a change is meant to alter charts):

    docker compose exec -e UPDATE_GOLDEN=1 backend pytest insights/test_golden.py
"""

import json
import os
import random
from datetime import date
from pathlib import Path

import pytest

from insights import engine
from insights.management.commands.seed_demo_transactions import build_rows
from insights.spec import resolve_period, validate_spec
from insights.templates import TEMPLATES

GOLDEN = Path(__file__).parent / "golden" / "engine_outputs.json"
TODAY = date(2026, 10, 15)
DASHBOARD_DATE = {"preset": "last_12_months"}


def _as_version_1(config: dict) -> dict:
    """A current template config as version 1 saved it: `compare: true` on the KPIs."""
    config = {key: value for key, value in config.items() if key != "kpi"}
    if config["chart"] == "kpi":
        config["compare"] = True
    return config | {"v": 1}


# Version-1 configs as the browser and the templates sent them: every chart, colour splits,
# KPI comparisons, "Other" folding, label sort, and each kind of x field.
CONFIGS = {
    f"template-{n}": _as_version_1(panel["config"])
    for n, panel in enumerate(TEMPLATES["overview"])
} | {
    "bar-merchant-top5": {"chart": "bar", "x": {"field": "merchant"}, "y": {"measure": "spend"},
                          "limit": 5},
    "bar-weekday-avg": {"chart": "bar", "x": {"field": "weekday"},
                        "y": {"measure": "spend", "agg": "avg"}},
    "bar-category-label-sort": {"chart": "bar", "x": {"field": "category"},
                                "y": {"measure": "count"}, "sort": "label"},
    "line-week-net": {"chart": "line", "x": {"field": "date", "granularity": "week"},
                      "y": {"measure": "net"}},
    "area-month-by-category": {"chart": "area", "x": {"field": "date", "granularity": "month"},
                               "y": {"measure": "spend"}, "color": {"field": "category"},
                               "stacked": True},
    "line-balance-last": {"chart": "line", "x": {"field": "date", "granularity": "month"},
                          "y": {"measure": "balance", "agg": "last"}},
    "donut-month-of-year": {"chart": "donut", "x": {"field": "month_of_year"},
                            "y": {"measure": "income"}},
    "kpi-count-no-compare": {"chart": "kpi", "y": {"measure": "count"}},
    "kpi-median-compare": {"chart": "kpi", "y": {"measure": "spend", "agg": "median"},
                           "compare": True, "filters": {"date": {"preset": "last_month"}}, "v": 1},
    "histogram-10-bins": {"chart": "histogram", "y": {"measure": "spend"}, "bins": 10},
    "bar-quarter-type": {"chart": "bar", "x": {"field": "date", "granularity": "quarter"},
                         "y": {"measure": "amount"}, "color": {"field": "txn_type"},
                         "v": 1},
}  # fmt: skip


def _rows() -> list[dict]:
    """Fixed fictional rows in the shape insights.services.load_rows gives the engine."""
    rows = build_rows(TODAY, months=12, scale=2, rng=random.Random(8))
    return [
        {
            "date": row["date"],
            "txn_type": row["txn_type"],
            "category_name": row["category"],
            "amount": row["amount"],
            "name": row["name"],
            "balance": row["balance"],
        }
        for row in rows
    ]


def _output(config: dict) -> dict:
    spec = validate_spec(config)
    period = resolve_period(spec["filters"]["date"], DASHBOARD_DATE, TODAY)
    return engine.run(spec, _rows(), period)


def _all_outputs() -> dict:
    return {name: _output(config) for name, config in CONFIGS.items()}


def test_saved_configs_produce_the_recorded_chart_data():
    outputs = json.loads(json.dumps(_all_outputs()))  # the same JSON form as the file
    if os.environ.get("UPDATE_GOLDEN"):
        GOLDEN.parent.mkdir(exist_ok=True)
        GOLDEN.write_text(json.dumps(outputs, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        pytest.skip("golden outputs recorded")
    expected = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert outputs.keys() == expected.keys()
    for name in expected:
        assert outputs[name] == expected[name], name

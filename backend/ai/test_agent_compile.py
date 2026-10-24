from datetime import date
from decimal import Decimal

import pytest

from ai.agent import compile as compiler
from ai.agent.compile import (
    Grounding,
    compile_intent,
    describe,
    granularity_for,
    ground,
    resolve_by_meaning,
    run_preview,
    spec_to_intent,
)
from ai.agent.context import AgentContext, CategoryIndex, CategoryRef, MerchantMatch
from ai.agent.errors import AgentError
from ai.agent.prompts import _EXAMPLE_CATEGORY, EXAMPLES
from ai.agent.schema import PanelIntent
from insights.spec import SpecError, validate_spec
from insights.templates import TEMPLATES
from transactions.tests import make_txn, make_user

TODAY = date(2026, 10, 25)
FOOD = CategoryRef("11111111-1111-4111-8111-111111111111", "Food")
GROCERIES = CategoryRef(_EXAMPLE_CATEGORY, "Groceries")
NAMES = ["Tastybites Cafe", "Tastybites Kitchen", "Fitzone Gym"]


def context(embed=None, merchants=NAMES):
    return AgentContext(
        user=None,
        today=TODAY,
        categories=CategoryIndex([FOOD, GROCERIES], [("food delivery", FOOD.id)]),
        first_date=date(2015, 1, 1),
        embed=embed,
        _merchants=list(merchants),
    )


def intent(**fields) -> PanelIntent:
    return PanelIntent(kind="panel", **fields)


def build(message="", dashboard_date=None, **fields):
    ctx = context()
    panel = intent(**fields)
    return compile_intent(
        panel, ground(panel, ctx), ctx, message=message, dashboard_date=dashboard_date
    )


# --- grounding ------------------------------------------------------------------------


def test_categories_become_ids_with_a_note_when_not_matched_by_name():
    grounding = ground(intent(categories=["food", "grocery", "Pets", "Food"]), context())
    assert grounding.categories == [FOOD.id, GROCERIES.id]
    assert grounding.notes == [
        "“grocery” was read as the category Groceries.",
        "No category matches “Pets”, so it was left out.",
    ]


def test_a_merchant_by_name_and_the_cache_that_saves_a_rescan():
    cache = {}
    grounding = ground(intent(merchant="Tastybites"), context(), cache)
    assert grounding.merchant == "tastybites"
    assert grounding.notes == ["“Tastybites” covers 2 merchants."]
    assert cache == {"tastybites": ["tastybites", "name", 2]}
    # No merchant names this time: the answer comes from the cache.
    again = ground(intent(merchant="TASTYBITES"), context(merchants=[]), cache)
    assert again.merchant == "tastybites"


def test_an_unknown_merchant_without_an_index_is_left_out_and_cached():
    cache = {}
    grounding = ground(intent(merchant="Riverstone"), context(), cache)
    assert grounding.merchant == "" and grounding.pending_merchant is None
    assert "not filtered by merchant" in grounding.notes[0]
    assert cache == {"riverstone": None}


def test_an_unknown_merchant_with_an_index_waits_for_a_search_by_meaning():
    cache = {}
    grounding = ground(intent(merchant="workout"), context(embed={"model": "m"}), cache)
    assert grounding.pending_merchant == "workout" and cache == {}

    resolve_by_meaning(grounding, MerchantMatch("fitzone gym", "meaning", 1), cache)
    assert grounding.merchant == "fitzone gym" and grounding.pending_merchant is None
    assert "matched by meaning" in grounding.notes[0]
    assert cache == {"workout": ["fitzone gym", "meaning", 1]}


def test_nothing_found_by_meaning_is_a_note():
    grounding = Grounding(pending_merchant="workout")
    resolve_by_meaning(grounding, None)
    assert grounding.merchant == "" and "not filtered" in grounding.notes[0]


# --- the compiler: golden cases ----------------------------------------------------------

CASES = [
    (
        "bar by category",
        dict(chart="bar", measure="spend", x="category"),
        "",
        {"chart": "bar", "x": {"field": "category"}, "y": {"measure": "spend", "agg": "sum"}},
        [],
    ),
    (
        "a date phrase in the message wins over the model",
        dict(chart="line", measure="spend", x="date", period="last_month", categories=["Food"]),
        "monthly food spend this year",
        {"filters": {"date": {"preset": "this_year"}, "type": None,
                     "categories": [FOOD.id], "merchant_contains": ""}},
        [],
    ),
    (
        "no chart and no x is a KPI",
        dict(measure="income"),
        "",
        {"chart": "kpi", "kpi": {"compare": "none", "sparkline": None, "direction": "auto",
                                 "secondary": []}},
        ["No chart type was given, so it is a kpi chart."],
    ),
    (
        "no measure is spend",
        dict(chart="kpi"),
        "",
        {"y": {"measure": "spend", "agg": "sum"}},
        ["No measure was given, so it shows spend."],
    ),
    (
        "a line by category runs over dates, split by colour",
        dict(chart="line", measure="spend", x="category", granularity="month"),
        "",
        {"x": {"field": "date", "granularity": "month"}, "color": {"field": "category"}},
        ["A line chart runs over dates, so category became the colour."],
    ),
    (
        "a pie cannot be split by colour",
        dict(chart="pie", measure="spend", x="category", color="txn_type"),
        "",
        {"x": {"field": "category"}},
        ["A pie can't be split by colour, so that was dropped."],
    ),
    (
        "a KPI has no x",
        dict(chart="kpi", measure="spend", x="category"),
        "",
        {"chart": "kpi"},
        ["A kpi has no x axis, so category was dropped."],
    ),
    (
        "an aggregation the measure does not allow",
        dict(chart="bar", measure="count", agg="avg", x="weekday"),
        "",
        {"y": {"measure": "count", "agg": "sum"}},
        ["Average does not apply to transactions, so it uses sum."],
    ),
    (
        "spend with a money-in filter",
        dict(chart="kpi", measure="spend", txn_type="credit"),
        "",
        {"filters": {"date": {"preset": "inherit"}, "type": None, "categories": [],
                     "merchant_contains": ""}},
        ["Spend already picks its own type, so the type filter was dropped."],
    ),
    (
        "top N on a categorical x",
        dict(chart="bar", measure="spend", x="merchant", limit=5, sort="label"),
        "",
        {"limit": 5, "sort": "label"},
        [],
    ),
    (
        "top N on a date axis",
        dict(chart="bar", measure="spend", x="date", granularity="month", limit=5),
        "",
        {"limit": 10, "sort": "measure_desc"},
        ["Top N and sorting only apply when x is not a date, so they were dropped."],
    ),
    (
        "a heatmap without rows",
        dict(chart="heatmap", measure="spend"),
        "",
        {"x": {"field": "weekday"}, "rows": {"field": "category"}},
        ["No x axis was given, so it shows weekday.",
         "A heatmap needs a second field for its rows, so it uses category."],
    ),
    (
        "rows outside a heatmap",
        dict(chart="bar", measure="spend", x="category", rows="weekday"),
        "",
        {"x": {"field": "category"}},
        ["Only a heatmap has rows, so that was dropped."],
    ),
    (
        "custom dates that are not valid",
        dict(chart="kpi", measure="spend", period="custom", date_from="2026-01-01"),
        "",
        {"filters": {"date": {"preset": "inherit"}, "type": None, "categories": [],
                     "merchant_contains": ""}},
        ["The custom dates were not valid, so the panel uses the dashboard period."],
    ),
    (
        "a moving average gets its default window",
        dict(chart="line", measure="spend", x="date", granularity="week", calc="moving_average"),
        "",
        {"calc": {"type": "moving_average", "window": 3}},
        [],
    ),
    (
        "a change gets its defaults and loses a stray window",
        dict(chart="bar", measure="spend", x="date", granularity="month", calc="change", window=4),
        "",
        {"calc": {"type": "change", "vs": "previous", "as": "percent"}},
        [],
    ),
    (
        "a calculation on a KPI",
        dict(chart="kpi", measure="spend", calc="running_total"),
        "",
        {"chart": "kpi"},
        ["A kpi has no calculations, so it was dropped."],
    ),
    (
        "a comparison outside a KPI",
        dict(chart="bar", measure="spend", x="category", compare="previous"),
        "",
        {"chart": "bar"},
        ["Comparisons only apply to KPI cards, so it was dropped."],
    ),
    (
        "a KPI against an average",
        dict(chart="kpi", measure="spend", compare="average", average_of=6,
             direction="down_is_good"),
        "",
        {"kpi": {"compare": "average", "average_of": 6, "sparkline": None,
                 "direction": "down_is_good", "secondary": []}},
        [],
    ),
]  # fmt: skip


@pytest.mark.parametrize("name, fields, message, expected, notes", CASES, ids=[c[0] for c in CASES])
def test_golden_cases(name, fields, message, expected, notes):
    compiled = build(message=message, **fields)
    for key, value in expected.items():
        assert compiled.spec[key] == value, key
    assert compiled.notes == notes
    assert validate_spec(compiled.spec) == compiled.spec  # what the panels endpoint will accept


@pytest.mark.parametrize(
    "fields",
    [
        dict(
            chart="pie", measure="net", x="category"
        ),  # a pie needs values that are never negative
        dict(chart="bar", measure="spend", x="category", calc="running_total"),  # needs dates
        dict(chart="bar", measure="spend", agg="avg", x="category", calc="percent_of_total"),
        dict(chart="histogram", measure="count"),
    ],
)
def test_what_only_the_model_can_fix_is_refused_not_guessed(fields):
    with pytest.raises(SpecError):
        build(**fields)


def test_a_not_a_panel_intent_does_not_compile():
    ctx = context()
    question = PanelIntent(kind="not_a_panel", reason="A question.")
    with pytest.raises(ValueError):
        compile_intent(question, Grounding(), ctx)


def test_the_title_is_the_models_or_the_summary():
    assert build(chart="kpi", measure="spend", title="My spend").title == "My spend"
    assert build(chart="kpi", measure="spend").title == "Spend · Dashboard period · KPI"


def test_the_returned_intent_carries_the_period_actually_used():
    compiled = build(message="spend in march 2026", chart="kpi", measure="spend", period="all")
    assert (compiled.intent.period, compiled.intent.date_from, compiled.intent.date_to) == (
        "custom",
        "2026-03-01",
        "2026-03-31",
    )


def test_grounding_notes_come_first():
    compiled = build(chart="kpi", categories=["Pets"])
    assert compiled.notes[0].startswith("No category matches")


# --- granularity ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "days, expected",
    [(1, "day"), (45, "day"), (46, "week"), (183, "week"), (184, "month"), (1098, "month"),
     (1099, "quarter")],
)  # fmt: skip
def test_granularity_follows_the_span(days, expected):
    start = date(2020, 1, 1)
    assert granularity_for(start, date.fromordinal(start.toordinal() + days - 1)) == expected


@pytest.mark.parametrize(
    "period, dashboard, expected",
    [
        ("this_month", None, "day"),
        ("last_3_months", None, "week"),
        ("last_12_months", None, "month"),
        ("all", None, "quarter"),  # from the first transaction in 2015
        (None, None, "week"),  # inherits; the dashboard inherits too: the default 3 months
        (None, {"preset": "this_year"}, "month"),
    ],
)
def test_an_unset_granularity_comes_from_the_period(period, dashboard, expected):
    compiled = build(dashboard_date=dashboard, chart="line", measure="spend", period=period)
    assert compiled.spec["x"] == {"field": "date", "granularity": expected}


def test_a_given_granularity_is_kept():
    compiled = build(chart="line", measure="spend", period="all", granularity="day")
    assert compiled.spec["x"]["granularity"] == "day"


# --- describe ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "spec, expected",
    [
        (
            {"chart": "bar", "x": {"field": "category"}, "y": {"measure": "spend"}},
            "Spend by category · Dashboard period · Bar",
        ),
        (
            {"chart": "line", "x": {"field": "date", "granularity": "week"},
             "color": {"field": "txn_type"}, "y": {"measure": "amount", "agg": "avg"},
             "filters": {"date": {"preset": "last_3_months"}}},
            "Average amount by date and type · Last 3 months · Line",
        ),
        (
            {"chart": "kpi", "y": {"measure": "count"},
             "filters": {"date": {"preset": "custom", "from": "2026-01-01", "to": "2026-03-31"}}},
            "Transactions · 1 Jan 2026 – 31 Mar 2026 · KPI",
        ),
        (
            {"chart": "histogram", "y": {"measure": "spend"}},
            "Spend · Dashboard period · Histogram",
        ),
    ],
)  # fmt: skip
def test_describe(spec, expected):
    assert describe(validate_spec(spec)) == expected


# --- the reverse: spec to intent ------------------------------------------------------------

PRESENTATION = ("orientation", "stacked", "series_colors", "format", "bind")
ROUND_TRIP = [panel["config"] for panel in TEMPLATES["overview"]] + [
    spec for _, spec, _ in EXAMPLES if isinstance(spec, dict)
]


def _without_presentation(spec: dict) -> dict:
    return {key: value for key, value in spec.items() if key not in PRESENTATION}


@pytest.mark.parametrize("spec", ROUND_TRIP)
def test_spec_to_intent_compiles_back_to_the_same_spec(spec):
    ctx = context()
    panel = spec_to_intent(spec, {GROCERIES.id: GROCERIES.name})
    compiled = compile_intent(panel, ground(panel, ctx), ctx)
    assert compiled.notes == []
    assert _without_presentation(compiled.spec) == _without_presentation(validate_spec(spec))


def test_spec_to_intent_leaves_defaults_unset():
    panel = spec_to_intent({"chart": "bar", "x": {"field": "merchant"}, "y": {"measure": "spend"}})
    assert (panel.agg, panel.limit, panel.sort, panel.period, panel.compare) == (None,) * 5


def test_spec_to_intent_skips_unknown_category_ids():
    spec = {"chart": "kpi", "y": {"measure": "spend"}, "filters": {"categories": [FOOD.id]}}
    assert spec_to_intent(spec).categories == []
    assert spec_to_intent(spec, {FOOD.id: "Food"}).categories == ["Food"]


def test_a_text_panel_has_no_intent():
    with pytest.raises(ValueError):
        spec_to_intent({"chart": "text", "text": "A note."})


# --- the preview ---------------------------------------------------------------------------


@pytest.fixture
def alice(db):
    return make_user("alice@example.com")


def preview(user, spec, dashboard=None):
    return run_preview(user, validate_spec(spec), dashboard or {}, TODAY, ["earlier note"])


def test_a_preview_runs_like_a_dashboard_panel(alice):
    make_txn(alice, date=date(2026, 10, 1), amount=Decimal("12.00"))
    result = preview(alice, {"chart": "kpi", "y": {"measure": "spend"}})
    assert result.error is None and result.notes == ["earlier note"]
    assert result.result["meta"]["chart"] == "kpi"


def test_too_many_points_coarsens_the_granularity(alice):
    make_txn(alice, date=date(2020, 1, 1))
    spec = {
        "chart": "line",
        "x": {"field": "date", "granularity": "day"},
        "y": {"measure": "spend"},
        "filters": {"date": {"preset": "all"}},
    }
    result = preview(alice, spec)
    assert result.error is None and result.spec["x"]["granularity"] == "week"
    assert result.notes[-1] == "The period had too many points, so it is grouped by week."


def test_coarsening_stops_after_its_limit_and_asks_the_model(alice, monkeypatch):
    monkeypatch.setattr(compiler, "MAX_COARSEN", 0)
    make_txn(alice, date=date(2020, 1, 1))
    spec = {
        "chart": "line",
        "x": {"field": "date", "granularity": "day"},
        "y": {"measure": "spend"},
        "filters": {"date": {"preset": "all"}},
    }
    result = preview(alice, spec)
    assert result.error["code"] == "too_many_points" and result.repairable


def test_a_calendar_over_a_year_shows_the_last_12_months(alice):
    make_txn(alice, date=date(2020, 1, 1))
    result = preview(alice, {"chart": "calendar", "y": {"measure": "spend"},
                             "filters": {"date": {"preset": "all"}}})  # fmt: skip
    assert result.error is None
    assert result.spec["filters"]["date"] == {"preset": "last_12_months"}


def test_too_many_rows_is_final(alice, settings):
    settings.INSIGHTS_MAX_ROWS = 0
    make_txn(alice, date=date(2026, 10, 1))
    result = preview(alice, {"chart": "kpi", "y": {"measure": "spend"}})
    assert result.error["code"] == "too_many_rows" and not result.repairable
    assert result.spec["chart"] == "kpi"  # kept, so the user can still edit it by hand


def test_any_other_error_goes_back_to_the_model(alice, monkeypatch):
    def failing(*args, **kwargs):
        return {"preview": {"error": {"code": "invalid_spec", "detail": "Something."}}}

    monkeypatch.setattr(compiler, "run_queries", failing)
    result = preview(alice, {"chart": "kpi", "y": {"measure": "spend"}})
    assert result.repairable and result.error["code"] == "invalid_spec"


def test_a_bad_dashboard_filter_is_the_requests_fault(alice):
    with pytest.raises(AgentError) as caught:
        preview(alice, {"chart": "kpi", "y": {"measure": "spend"}}, {"filters": {"type": "x"}})
    assert caught.value.code == "invalid_filters"


def test_the_preview_does_not_change_the_callers_spec(alice):
    make_txn(alice, date=date(2020, 1, 1))
    spec = validate_spec(
        {"chart": "line", "x": {"field": "date", "granularity": "day"},
         "y": {"measure": "spend"}, "filters": {"date": {"preset": "all"}}}
    )  # fmt: skip
    run_preview(alice, spec, {}, TODAY, [])
    assert spec["x"]["granularity"] == "day"

"""Several measures on one chart, and calculated fields on more chart types."""

import json
from datetime import date
from decimal import Decimal

import pytest

from datasources.services import create_source, first_source, rename_source
from insights import services
from insights.models import Dashboard, Panel
from insights.services import PANEL_CONFIG, rename_source_in_panels
from insights.spec import MAX_EXTRA_MEASURES, MAX_SERIES_LABEL, SpecError, catalogue, validate_spec
from transactions.models import TransferLink
from transactions.tests import make_txn, make_user
from vault.services import UserCipher

D = Decimal
TODAY = date(2026, 4, 1)
SPRING = {"date": {"preset": "custom", "from": "2026-01-01", "to": "2026-03-31"}}
MONTHLY = {"field": "date", "granularity": "month"}
SPEND, INCOME = {"measure": "spend"}, {"measure": "income"}


def formula(text: str, form: str = "money", **extra) -> dict:
    return {"measure": "formula", "formula": {"expression": text, "as": form}, **extra}


def chart(*measures, kind="line", x=None, **extra) -> dict:
    first, *also = measures
    spec = {"chart": kind, "x": x or MONTHLY, "y": first, **extra}
    return {**spec, "also": also} if also else spec


# --- what a spec may hold ------------------------------------------------------------------------


def test_a_panel_with_one_measure_stays_exactly_as_it_was():
    clean = validate_spec(chart(SPEND))
    assert "also" not in clean
    assert clean["y"] == {"measure": "spend", "agg": "sum"}


@pytest.mark.parametrize("kind", ["line", "area", "bar"])
def test_several_measures_work_on_these_charts(kind):
    clean = validate_spec(chart(SPEND, INCOME, kind=kind))
    assert clean["also"] == [{"measure": "income", "agg": "sum"}]


@pytest.mark.parametrize("kind", ["pie", "donut", "heatmap", "calendar", "histogram", "kpi"])
def test_other_charts_show_one_measure(kind):
    spec = {"chart": kind, "y": SPEND, "also": [INCOME]}
    if kind in ("pie", "donut"):
        spec["x"] = {"field": "category"}
    if kind == "heatmap":
        spec |= {"x": {"field": "weekday"}, "rows": {"field": "category"}}
    with pytest.raises(SpecError, match="Several measures work on"):
        validate_spec(spec)


def test_a_chart_has_a_limit_on_measures():
    assert validate_spec(chart(SPEND, *[INCOME] * MAX_EXTRA_MEASURES))
    with pytest.raises(SpecError, match="at most"):
        validate_spec(chart(SPEND, *[INCOME] * (MAX_EXTRA_MEASURES + 1)))


def test_a_measure_can_have_a_name():
    clean = validate_spec(chart({**SPEND, "label": "  Out  "}, {**INCOME, "label": "In"}))
    assert clean["y"]["label"] == "Out"
    assert clean["also"][0]["label"] == "In"


def test_a_name_has_a_limit():
    with pytest.raises(SpecError, match="label"):
        validate_spec(chart({**SPEND, "label": "x" * (MAX_SERIES_LABEL + 1)}))


def test_each_measure_follows_its_own_rules():
    with pytest.raises(SpecError):
        validate_spec(chart(SPEND, {"measure": "balance", "agg": "sum"}))
    with pytest.raises(SpecError):
        validate_spec(chart(SPEND, {"measure": "nonsense"}))
    with pytest.raises(SpecError, match="Formula"):
        validate_spec(chart(SPEND, formula("not a formula (")))


def test_validating_twice_changes_nothing():
    clean = validate_spec(chart(SPEND, formula("spend / days", label="Daily")))
    assert validate_spec(clean) == clean


def test_a_calculation_must_suit_every_measure():
    assert validate_spec(chart(SPEND, INCOME, calc={"type": "running_total"}))
    with pytest.raises(SpecError, match="add up"):
        validate_spec(chart(SPEND, {"measure": "balance"}, calc={"type": "running_total"}))
    with pytest.raises(SpecError, match="never negative"):
        validate_spec(
            chart(
                SPEND,
                {"measure": "net"},
                kind="bar",
                x={"field": "category"},
                calc={"type": "percent_of_total"},
            )
        )


def test_the_catalogue_tells_the_editor_the_rules():
    offered = catalogue()
    assert offered["series"] == {
        "charts": ["bar", "line", "area"],
        "max_extra": MAX_EXTRA_MEASURES,
        "max_label": MAX_SERIES_LABEL,
    }
    assert "histogram" not in offered["formula"]["charts"]
    assert {"pie", "donut", "calendar", "heatmap"} <= set(offered["formula"]["charts"])


# --- running them --------------------------------------------------------------------------------


@pytest.fixture
def alice(db):
    user = make_user("alice@example.com")
    user.oak = first_source(user)
    user.river = create_source(user, UserCipher(user), "River Bank")
    return user


def add(user, amount, kind="debit", day=date(2026, 1, 5), source=None, category="Food", balance=None):
    return make_txn(
        user,
        amount=D(amount),
        txn_type=kind,
        date=day,
        data_source=source or user.oak,
        category=user.category_set.get(name=category),
        balance=None if balance is None else D(balance),
        description=f"{amount}/{kind}/{day}/{source}/{category}",
    )


def run(user, spec):
    result = services.run_queries(user, SPRING, [{"key": "p", "spec": spec}], TODAY)["p"]
    assert "error" not in result, result
    return result


def test_each_measure_gets_its_own_rows(alice):
    add(alice, "30.00")
    add(alice, "100.00", "credit", date(2026, 2, 5))
    result = run(alice, chart(SPEND, INCOME))
    assert result["columns"] == ["x", "series", "value"]
    assert result["rows"] == [
        ["2026-01-01", 0, "30.00"],
        ["2026-02-01", 0, "0.00"],
        ["2026-03-01", 0, "0.00"],
        ["2026-01-01", 1, "0.00"],
        ["2026-02-01", 1, "100.00"],
        ["2026-03-01", 1, "0.00"],
    ]


def test_a_formula_sits_beside_a_plain_measure(alice):
    add(alice, "30.00")
    add(alice, "120.00", "credit")
    rows = run(alice, chart(SPEND, formula("net / income * 100", "percent")))["rows"]
    assert ["2026-01-01", 1, "75.00"] in rows


def test_measures_split_by_colour_keep_both(alice):
    add(alice, "30.00")
    add(alice, "5.00", category="Rent")
    add(alice, "100.00", "credit", category="Salary")
    result = run(alice, chart(SPEND, INCOME, kind="bar", x={"field": "date", "granularity": "month"}, color={"field": "category"}))
    assert result["columns"] == ["x", "series", "color", "value"]
    january = [row for row in result["rows"] if row[0] == "2026-01-01"]
    assert ["2026-01-01", 0, "Food", "30.00"] in january
    assert ["2026-01-01", 0, "Rent", "5.00"] in january
    assert ["2026-01-01", 1, "Salary", "100.00"] in january


def test_the_first_measure_picks_the_bars_and_the_rest_follow(alice):
    add(alice, "10.00", category="Food")
    add(alice, "90.00", category="Rent")
    add(alice, "500.00", "credit", category="Salary")
    spec = chart(SPEND, INCOME, kind="bar", x={"field": "category"}, limit=1)
    rows = run(alice, spec)["rows"]
    assert {row[0] for row in rows} == {"Rent"}  # the top spend, and income follows it
    assert len(rows) == 2


def test_nothing_folds_into_other_with_several_measures(alice):
    add(alice, "10.00", category="Food")
    add(alice, "90.00", category="Rent")
    spec = chart(SPEND, INCOME, kind="bar", x={"field": "category"}, limit=1)
    assert "Other" not in {row[0] for row in run(alice, spec)["rows"]}


def test_a_calculation_runs_on_each_measure(alice):
    add(alice, "30.00")
    add(alice, "20.00", day=date(2026, 2, 5))
    add(alice, "100.00", "credit", date(2026, 2, 5))
    rows = run(alice, chart(SPEND, INCOME, calc={"type": "running_total"}))["rows"]
    assert ["2026-03-01", 0, "50.00"] in rows
    assert ["2026-03-01", 1, "100.00"] in rows


def test_balances_sit_beside_other_measures(alice):
    add(alice, "10.00", day=date(2025, 12, 20), balance="100.00")
    add(alice, "20.00", day=date(2026, 2, 5), balance="80.00")
    rows = run(alice, chart(SPEND, {"measure": "balance"}))["rows"]
    assert ["2026-01-01", 1, "100.00"] in rows  # carried in from before the period
    assert ["2026-03-01", 1, "80.00"] in rows  # and carried through a quiet month


def test_a_plain_measure_keeps_to_the_panels_sources_beside_a_named_one(alice):
    add(alice, "30.00", source=alice.oak)
    add(alice, "12.00", source=alice.river)
    spec = chart(
        SPEND, formula("[River Bank].spend"), filters={"data_sources": [str(alice.oak.pk)]}
    )
    rows = run(alice, spec)["rows"]
    assert ["2026-01-01", 0, "30.00"] in rows  # only the panel's source
    assert ["2026-01-01", 1, "12.00"] in rows  # the formula reads the source it names


def test_transfers_cancel_for_plain_measures_beside_a_named_one(alice):
    debit =add(alice, "50.00", source=alice.oak)
    credit = add(alice, "50.00", "credit", source=alice.river)
    TransferLink.objects.create(user=alice, debit=debit, credit=credit)
    rows = run(alice, chart(SPEND, formula("Main.spend")))["rows"]
    assert ["2026-01-01", 0, "0.00"] in rows
    assert ["2026-01-01", 1, "50.00"] in rows


def test_an_unknown_source_in_any_measure_is_reported(alice):
    result = services.run_queries(
        alice, SPRING, [{"key": "p", "spec": chart(SPEND, formula("Nowhere.spend"))}], TODAY
    )["p"]
    assert result["error"]["code"] == "unknown_data_source"


def test_a_field_needed_only_by_a_later_measure_is_loaded(alice):
    add(alice, "30.00")
    rows = run(alice, chart(SPEND, formula('SUM(IF CONTAINS([Merchant], "tasty") THEN 1 END)', "number")))["rows"]
    assert ["2026-01-01", 1, "1.00"] in rows


def test_the_rows_of_one_measure_agree_with_its_mark(alice):
    add(alice, "30.00")
    add(alice, "100.00", "credit")
    only_income = chart(INCOME)  # what the page sends after a click on the income line
    mark = {"date": {"from": "2026-01-01", "to": "2026-01-31"}}
    body = services.list_rows(alice, SPRING, only_income, mark, today=TODAY)
    assert body["value"] == "100.00"


# --- renaming a source --------------------------------------------------------------------------


def test_renaming_a_source_reaches_every_measure(alice):
    cipher = UserCipher(alice)
    dashboard = Dashboard.objects.create(user=alice, name_enc=b"x")
    spec = validate_spec(chart(formula("Main.spend"), formula("Main.income")))
    panel = Panel.objects.create(
        dashboard=dashboard,
        title_enc=b"x",
        config_enc=cipher.encrypt(json.dumps(spec).encode(), PANEL_CONFIG),
        x=0,
        y=0,
        w=6,
        h=4,
    )
    rename_source(alice.oak, cipher, "Oak")
    assert rename_source_in_panels(alice, cipher, "Main", "Oak") == 1
    panel.refresh_from_db()
    saved = json.loads(cipher.decrypt(bytes(panel.config_enc), PANEL_CONFIG))
    assert saved["y"]["formula"]["expression"] == "Oak.spend"
    assert saved["also"][0]["formula"]["expression"] == "Oak.income"


def test_a_source_named_only_by_a_later_measure_counts_as_in_use(alice):
    cipher = UserCipher(alice)
    dashboard = Dashboard.objects.create(user=alice, name_enc=b"x")
    spec = validate_spec(chart(SPEND, formula("[River Bank].spend")))
    Panel.objects.create(
        dashboard=dashboard,
        title_enc=b"x",
        config_enc=cipher.encrypt(json.dumps(spec).encode(), PANEL_CONFIG),
        x=0,
        y=0,
        w=6,
        h=4,
    )
    assert services.panels_using_source(alice, cipher, str(alice.river.pk), "River Bank") == 1


# --- calculated fields on more charts ------------------------------------------------------------


def test_a_formula_can_size_a_pie(alice):
    add(alice, "30.00", category="Food")
    add(alice, "90.00", category="Rent")
    spec = {"chart": "pie", "x": {"field": "category"}, "y": formula("spend * 2")}
    assert sorted(run(alice, spec)["rows"]) == [["Food", "60.00"], ["Rent", "180.00"]]


def test_a_formula_can_size_a_donut(alice):
    add(alice, "30.00")
    spec = {"chart": "donut", "x": {"field": "category"}, "y": formula("spend + 1")}
    assert run(alice, spec)["rows"] == [["Food", "31.00"]]


def test_a_formula_can_colour_a_calendar(alice):
    add(alice, "30.00", day=date(2026, 1, 5))
    spec = {"chart": "calendar", "y": formula("spend - 100")}
    assert run(alice, spec)["rows"] == [["2026-01-05", "-70.00"]]


def test_a_calendar_formula_sees_one_day(alice):
    add(alice, "30.00", day=date(2026, 1, 5))
    spec = {"chart": "calendar", "y": formula("days", "number")}
    assert run(alice, spec)["rows"] == [["2026-01-05", "1.00"]]


def test_a_formula_can_colour_a_heatmap(alice):
    add(alice, "30.00", day=date(2026, 1, 5))
    spec = {
        "chart": "heatmap",
        "x": {"field": "weekday"},
        "rows": {"field": "category"},
        "y": formula("spend / count"),
    }
    assert run(alice, spec)["rows"] == [[0, "Food", "30.00"]]


def test_a_heatmap_formula_counts_the_days_of_its_cell(alice):
    add(alice, "30.00", day=date(2026, 1, 5))  # a Monday: 13 Mondays from January to March
    spec = {
        "chart": "heatmap",
        "x": {"field": "weekday"},
        "rows": {"field": "category"},
        "y": formula("days", "number"),
    }
    assert run(alice, spec)["rows"] == [[0, "Food", "13.00"]]

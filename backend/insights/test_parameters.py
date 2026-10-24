"""Dashboard parameters: Top N, date grouping, measure and comparison, followed only where a
panel is bound to them."""

from datetime import date
from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from categories.models import Category
from insights import services
from insights.models import Dashboard
from insights.spec import (
    BINDINGS,
    PARAMETER_DEFAULTS,
    SPEC_VERSION,
    SpecError,
    apply_parameters,
    catalogue,
    validate_bind,
    validate_parameters,
    validate_spec,
)
from insights.test_models import make_dashboard
from transactions.tests import make_txn, make_user
from vault.services import UserCipher

pytestmark = pytest.mark.django_db

D = Decimal
BAR = {"chart": "bar", "x": {"field": "category"}, "y": {"measure": "spend"}}
LINE = {"chart": "line", "x": {"field": "date", "granularity": "month"}, "y": {"measure": "spend"}}
KPI = {"chart": "kpi", "y": {"measure": "spend"}}


def params(**override):
    return {**PARAMETER_DEFAULTS, **override}


# --- the parameter values -----------------------------------------------------------------


def test_missing_parameters_take_their_defaults():
    assert validate_parameters(None) == PARAMETER_DEFAULTS
    assert validate_parameters({}) == PARAMETER_DEFAULTS
    assert validate_parameters({"top_n": 5}) == params(top_n=5)


def test_clean_parameters_validate_to_themselves():
    clean = params(top_n=3, granularity="week", measure="net", comparison="year_ago")
    assert validate_parameters(clean) == clean


@pytest.mark.parametrize(
    "raw",
    [
        {"top_n": 0},
        {"top_n": 51},
        {"top_n": True},
        {"top_n": "5"},
        {"granularity": "hour"},
        {"measure": "balance"},
        {"measure": "count"},
        {"comparison": "average"},
        {"comparison": "none"},
        {"colour": "red"},
        ["top_n"],
    ],
)
def test_impossible_parameter_values_are_refused(raw):
    with pytest.raises(SpecError):
        validate_parameters(raw)


def test_the_catalogue_describes_the_parameters():
    offered = catalogue()["parameters"]
    assert offered["defaults"] == PARAMETER_DEFAULTS
    assert offered["bindings"] == BINDINGS
    assert offered["top_n"] == [1, 50] and offered["measures"] == ["spend", "income", "net"]


# --- binding a panel -----------------------------------------------------------------------


def test_a_bound_panel_keeps_its_own_values_and_its_binding():
    spec = validate_spec({**BAR, "limit": 5, "bind": {"limit": "top_n", "measure": "measure"}})
    assert spec["limit"] == 5 and spec["bind"] == {"limit": "top_n", "measure": "measure"}
    assert validate_spec(spec) == spec


def test_a_panel_without_bindings_has_no_bind_key():
    assert "bind" not in validate_spec(BAR)
    assert "bind" not in validate_spec({**BAR, "bind": {}})
    assert "bind" not in validate_spec({**BAR, "bind": None})


@pytest.mark.parametrize(
    "raw, bind",
    [
        (BAR, {"limit": "granularity"}),  # the wrong parameter for the field
        (BAR, {"colour": "measure"}),  # a field that can't be bound
        (BAR, {"granularity": "granularity"}),  # no date axis to group
        (BAR, {"compare": "comparison"}),  # only KPIs compare
        (BAR, {"vs": "comparison"}),  # no change calculation
        (LINE, {"limit": "top_n"}),  # a line has no top N
        (KPI, {"limit": "top_n"}),
        (BAR, "limit"),
    ],
)
def test_bindings_a_panel_cannot_use_are_refused(raw, bind):
    with pytest.raises(SpecError):
        validate_spec({**raw, "bind": bind})


def test_each_binding_is_accepted_where_the_panel_has_the_field():
    assert validate_spec({**LINE, "bind": {"granularity": "granularity"}})["bind"]
    assert validate_spec({**KPI, "bind": {"compare": "comparison"}})["bind"]
    change = {**LINE, "calc": {"type": "change"}, "bind": {"vs": "comparison"}}
    assert validate_spec(change)["bind"] == {"vs": "comparison"}
    heatmap = {**BAR, "chart": "heatmap", "rows": {"field": "weekday"}, "bind": {"limit": "top_n"}}
    assert validate_spec(heatmap)["bind"]


def test_a_text_panel_cannot_be_bound():
    with pytest.raises(SpecError):
        validate_spec({"chart": "text", "text": "hi", "bind": {"measure": "measure"}})


def test_validate_bind_returns_none_for_nothing():
    assert validate_bind(None, validate_spec(BAR)) is None


def test_older_specs_upgrade_untouched():
    for version in range(1, SPEC_VERSION):
        assert "bind" not in validate_spec({**BAR, "v": version})


# --- applying the values --------------------------------------------------------------------


def test_an_unbound_spec_is_returned_as_it_is():
    spec = validate_spec(BAR)
    assert apply_parameters(spec, params(top_n=3)) is spec


def test_a_bound_field_follows_the_parameter_and_the_rest_do_not():
    spec = validate_spec({**BAR, "limit": 7, "sort": "label", "bind": {"limit": "top_n"}})
    applied = apply_parameters(spec, params(top_n=3, measure="income"))
    assert applied["limit"] == 3
    assert applied["y"]["measure"] == "spend"  # not bound: keeps its own
    assert applied["sort"] == "label" and "bind" not in applied


def test_each_binding_sets_its_own_field():
    top = apply_parameters(validate_spec({**BAR, "bind": {"limit": "top_n"}}), params(top_n=4))
    assert top["limit"] == 4
    weekly = apply_parameters(
        validate_spec({**LINE, "bind": {"granularity": "granularity"}}), params(granularity="week")
    )
    assert weekly["x"]["granularity"] == "week"
    income = apply_parameters(
        validate_spec({**BAR, "bind": {"measure": "measure"}}), params(measure="income")
    )
    assert income["y"]["measure"] == "income"
    kpi = apply_parameters(
        validate_spec({**KPI, "bind": {"compare": "comparison"}}), params(comparison="year_ago")
    )
    assert kpi["kpi"]["compare"] == "year_ago"
    change = {**LINE, "calc": {"type": "change"}, "bind": {"vs": "comparison"}}
    assert (
        apply_parameters(validate_spec(change), params(comparison="year_ago"))["calc"]["vs"]
        == "year_ago"
    )


def test_binding_the_comparison_replaces_an_average_comparison_cleanly():
    spec = validate_spec(
        {**KPI, "kpi": {"compare": "average", "average_of": 6}, "bind": {"compare": "comparison"}}
    )
    applied = apply_parameters(spec, params(comparison="previous"))
    assert applied["kpi"]["compare"] == "previous" and "average_of" not in applied["kpi"]


def test_changing_the_measure_resets_an_aggregation_it_cannot_have():
    spec = validate_spec(
        {
            "chart": "line",
            "x": LINE["x"],
            "y": {"measure": "balance"},
            "bind": {"measure": "measure"},
        }
    )
    assert spec["y"]["agg"] == "last"
    assert apply_parameters(spec, params(measure="spend"))["y"]["agg"] == "sum"
    keep = validate_spec(
        {**BAR, "y": {"measure": "spend", "agg": "avg"}, "bind": {"measure": "measure"}}
    )
    assert apply_parameters(keep, params(measure="income"))["y"]["agg"] == "avg"


def test_a_value_that_does_not_fit_one_panel_is_that_panels_own_error():
    pie = validate_spec(
        {
            "chart": "pie",
            "x": {"field": "category"},
            "y": {"measure": "spend"},
            "bind": {"measure": "measure"},
        }
    )
    with pytest.raises(SpecError) as caught:
        apply_parameters(pie, params(measure="net"))
    assert caught.value.code == "parameter_conflict"
    assert "don't fit this panel" in caught.value.detail


# --- through the batch ----------------------------------------------------------------------


@pytest.fixture
def alice(db):
    user = make_user("alice@example.com")
    for day, amount, name in ((5, "100", "Food"), (6, "30", "Bills"), (7, "20", "Health")):
        category = Category.objects.get(user=user, name=name)
        make_txn(
            user,
            date=date(2026, 3, day),
            amount=D(amount),
            description=f"d{day}",
            category=category,
        )
    return user


def batch(user, queries, parameters=None):
    filters = {"date": {"preset": "custom", "from": "2026-03-01", "to": "2026-03-31"}}
    return services.run_queries(
        user, filters, queries, today=date(2026, 4, 1), parameters=parameters
    )


def test_a_bound_panel_follows_the_default_when_no_parameters_are_sent(alice):
    bound = {**BAR, "bind": {"limit": "top_n"}, "limit": 1}
    rows = batch(alice, [{"key": "a", "spec": bound}])["a"]["rows"]
    assert rows == [
        ["Food", "100.00"],
        ["Bills", "30.00"],
        ["Health", "20.00"],
    ]  # top_n defaults to 10
    unbound = batch(alice, [{"key": "a", "spec": {**BAR, "limit": 1}}])["a"]["rows"]
    assert unbound == [["Food", "100.00"], ["Other", "50.00"]]  # its own limit, untouched


def test_the_parameters_in_the_request_drive_only_the_bound_panels(alice):
    bound = {**LINE, "bind": {"granularity": "granularity"}}
    unbound = {**LINE}
    queries = [{"key": "bound", "spec": bound}, {"key": "unbound", "spec": unbound}]
    results = batch(alice, queries, {"granularity": "day"})
    assert (
        results["bound"]["meta"]["x"]["granularity"] == "day"
        and len(results["bound"]["rows"]) == 31
    )
    assert (
        results["unbound"]["meta"]["x"]["granularity"] == "month"
        and len(results["unbound"]["rows"]) == 1
    )


def test_a_conflict_breaks_one_panel_not_the_batch(alice):
    pie = {
        "chart": "pie",
        "x": {"field": "category"},
        "y": {"measure": "spend"},
        "bind": {"measure": "measure"},
    }
    queries = [{"key": "pie", "spec": pie}, {"key": "bar", "spec": BAR}]
    results = batch(alice, queries, {"measure": "net"})
    assert results["pie"]["error"]["code"] == "parameter_conflict"
    assert "rows" in results["bar"]


def test_bad_parameters_in_the_request_are_refused(alice):
    with pytest.raises(SpecError):
        batch(alice, [{"key": "a", "spec": BAR}], {"top_n": 99})


# --- saving them on the dashboard -----------------------------------------------------------------


def as_user(user):
    api = APIClient()
    api.force_authenticate(user)
    return api


def test_a_new_dashboard_reports_the_default_parameters():
    alice = make_user("alice@example.com")
    dashboard = make_dashboard(alice)
    body = as_user(alice).get(f"/api/dashboards/{dashboard.id}/").json()
    assert body["settings"] == {"parameters": PARAMETER_DEFAULTS}


def test_saved_parameters_come_back_with_the_dashboard_and_are_encrypted():
    alice = make_user("alice@example.com")
    dashboard = make_dashboard(alice)
    api = as_user(alice)

    saved = api.put(
        f"/api/dashboards/{dashboard.id}/settings/",
        {"parameters": {"top_n": 3, "measure": "income"}},
        format="json",
    )

    assert saved.status_code == 200
    assert saved.json() == {"parameters": params(top_n=3, measure="income")}
    assert (
        api.get(f"/api/dashboards/{dashboard.id}/").json()["settings"]["parameters"]["top_n"] == 3
    )
    stored = Dashboard.objects.get(pk=dashboard.pk).settings_enc
    assert b"income" not in bytes(stored) and b"top_n" not in bytes(stored)
    assert services.decrypt_parameters(UserCipher(alice), stored)["measure"] == "income"


def test_saving_bad_parameters_is_a_400_and_changes_nothing():
    alice = make_user("alice@example.com")
    dashboard = make_dashboard(alice)
    api = as_user(alice)
    api.put(
        f"/api/dashboards/{dashboard.id}/settings/", {"parameters": {"top_n": 4}}, format="json"
    )

    for body in (
        {"parameters": {"top_n": 0}},
        {"parameters": {"nope": 1}},
        {"parameters": "x"},
        {},
    ):
        assert (
            api.put(f"/api/dashboards/{dashboard.id}/settings/", body, format="json").status_code
            == 400
        )
    assert (
        api.get(f"/api/dashboards/{dashboard.id}/").json()["settings"]["parameters"]["top_n"] == 4
    )


def test_nobody_else_can_read_or_change_a_dashboards_parameters():
    alice, bob = make_user("alice@example.com"), make_user("bob@example.com")
    dashboard = make_dashboard(alice)
    response = as_user(bob).put(
        f"/api/dashboards/{dashboard.id}/settings/", {"parameters": {"top_n": 2}}, format="json"
    )
    assert response.status_code == 404
    assert Dashboard.objects.get(pk=dashboard.pk).settings_enc is None
    assert as_user(bob).get(f"/api/dashboards/{dashboard.id}/").status_code == 404


def test_the_settings_endpoint_needs_a_login():
    alice = make_user("alice@example.com")
    dashboard = make_dashboard(alice)
    response = APIClient().put(
        f"/api/dashboards/{dashboard.id}/settings/", {"parameters": {}}, format="json"
    )
    assert response.status_code in (401, 403)


def test_the_query_endpoint_accepts_parameters(alice):
    api = as_user(alice)
    body = {
        "filters": {"date": {"preset": "custom", "from": "2026-03-01", "to": "2026-03-31"}},
        "parameters": {"top_n": 1},
        "queries": [{"key": "a", "spec": {**BAR, "bind": {"limit": "top_n"}}}],
    }
    ok = api.post("/api/insights/query/", body, format="json")
    assert ok.status_code == 200 and ok.json()["results"]["a"]["rows"][-1][0] == "Other"
    bad = api.post("/api/insights/query/", {**body, "parameters": {"top_n": 99}}, format="json")
    assert bad.status_code == 400

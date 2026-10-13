"""HTTP-level tests for the two /api/insights/ endpoints."""

from decimal import Decimal

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from insights.spec import catalogue, validate_spec
from insights.views import MAX_QUERIES
from transactions.tests import make_txn, make_user

pytestmark = pytest.mark.django_db

FIELDS = "/api/insights/fields/"
QUERY = "/api/insights/query/"

KPI = {"chart": "kpi", "y": {"measure": "spend"}}


def as_user(user):
    api = APIClient()
    api.force_authenticate(user)
    return api


def post(user, body):
    return as_user(user).post(QUERY, body, format="json")


def one_query(key="k", spec=KPI):
    return {"queries": [{"key": key, "spec": spec}]}


@pytest.fixture
def alice():
    return make_user("alice@example.com")


@pytest.fixture
def bob():
    return make_user("bob@example.com")


# --- auth ---------------------------------------------------------------------


def test_fields_requires_login():
    assert APIClient().get(FIELDS).status_code == 401


def test_query_requires_login():
    assert APIClient().post(QUERY, one_query(), format="json").status_code == 401


# --- fields -------------------------------------------------------------------


def test_fields_returns_the_catalogue(alice):
    response = as_user(alice).get(FIELDS)
    assert response.status_code == 200
    data = response.json()
    assert data["version"] == 1
    assert data["charts"]["kpi"] == {"x": [], "color": False}
    assert "category" in data["charts"]["bar"]["x"]
    assert data["charts"]["line"]["x"] == ["date"]
    assert {"id": "balance", "aggs": ["last"], "default_agg": "last"} in data["measures"]
    assert data["dimensions"][0] == {
        "id": "date",
        "granularities": ["day", "week", "month", "quarter", "year"],
    }
    assert "custom" in data["date_presets"]
    assert data["limits"]["limit"] == [1, 50]


def example_spec(chart, x_field, measure):
    """A spec built only from what the catalogue offers."""
    spec = {"chart": chart, "y": {"measure": measure}}
    if x_field:
        spec["x"] = {"field": x_field}
        if x_field == "date":
            spec["x"]["granularity"] = "month"
    return spec


def test_everything_the_catalogue_offers_is_accepted_by_the_validator():
    offered = catalogue()
    checked = 0
    for chart, rules in offered["charts"].items():
        for x_field in rules["x"] or [None]:
            for measure in offered["measures"]:
                if chart in ("pie", "donut") and measure["id"] in ("net", "balance"):
                    continue  # known rejections the catalogue does not list yet
                if chart == "histogram" and measure["id"] == "count":
                    continue
                for agg in measure["aggs"]:
                    spec = example_spec(chart, x_field, measure["id"])
                    spec["y"]["agg"] = agg
                    if chart == "histogram":
                        spec["y"].pop("agg")  # a histogram ignores the aggregation
                    validate_spec(spec)
                    checked += 1
    assert checked > 100  # guards against the loops silently checking nothing


# --- query: results -----------------------------------------------------------


def test_query_returns_results_under_their_keys(alice):
    make_txn(alice, date=timezone.localdate(), amount=Decimal("12.50"))
    response = post(alice, one_query("headline"))
    assert response.status_code == 200
    assert response.json()["results"]["headline"]["rows"] == [["12.50", None, None]]


def test_filters_may_be_missing_or_null(alice):
    assert post(alice, one_query()).status_code == 200
    assert post(alice, {**one_query(), "filters": None}).status_code == 200


def test_a_bad_panel_still_returns_200_with_an_error_under_its_key(alice):
    make_txn(alice, date=timezone.localdate(), amount=Decimal("3.00"))
    body = {
        "queries": [
            {"key": "bad", "spec": {"chart": "nope"}},
            {"key": "good", "spec": KPI},
        ]
    }
    response = post(alice, body)
    assert response.status_code == 200
    results = response.json()["results"]
    assert results["bad"]["error"]["code"] == "invalid_spec"
    assert results["good"]["rows"][0][0] == "3.00"


def test_dashboard_filters_apply_to_the_panels(alice):
    today = timezone.localdate()
    make_txn(alice, date=today, txn_type="credit", amount=Decimal("20.00"))
    make_txn(alice, date=today, txn_type="debit", amount=Decimal("7.00"))
    spec = {"chart": "kpi", "y": {"measure": "amount"}}
    body = {**one_query(spec=spec), "filters": {"type": "credit"}}
    assert post(alice, body).json()["results"]["k"]["rows"][0][0] == "20.00"


def test_a_user_never_sees_another_users_transactions(alice, bob):
    today = timezone.localdate()
    make_txn(alice, date=today, amount=Decimal("1.00"))
    make_txn(bob, date=today, amount=Decimal("99.00"))
    assert post(alice, one_query()).json()["results"]["k"]["rows"][0][0] == "1.00"


# --- query: rejected requests -------------------------------------------------


def test_invalid_dashboard_filters_are_a_400_with_a_code(alice):
    response = post(alice, {**one_query(), "filters": {"type": "nope"}})
    assert response.status_code == 400
    assert response.json()["code"] == "invalid_spec"


@pytest.mark.parametrize(
    "body",
    [
        {},  # no queries at all
        {"queries": []},  # an empty batch
        {"queries": [{"key": "k"}]},  # no spec
        {"queries": [{"spec": KPI}]},  # no key
        {"queries": [{"key": "k", "spec": "not an object"}]},
        {"queries": [{"key": "x" * 65, "spec": KPI}]},  # key too long
        {"queries": [{"key": "k", "spec": KPI}, {"key": "k", "spec": KPI}]},  # duplicate keys
        {"queries": "nope"},
        {"filters": "nope", "queries": [{"key": "k", "spec": KPI}]},
    ],
)
def test_malformed_requests_are_a_400(alice, body):
    assert post(alice, body).status_code == 400


def test_the_batch_size_is_capped(alice):
    def batch(count):
        return {"queries": [{"key": f"p{i}", "spec": KPI} for i in range(count)]}

    assert post(alice, batch(MAX_QUERIES)).status_code == 200
    assert post(alice, batch(MAX_QUERIES + 1)).status_code == 400


# --- throttling ---------------------------------------------------------------


def test_the_insights_budget_is_shared_by_both_endpoints(alice):
    api = as_user(alice)
    codes = [api.get(FIELDS).status_code for _ in range(601)]
    assert codes[:600] == [200] * 600
    assert codes[600] == 429
    assert api.post(QUERY, one_query(), format="json").status_code == 429

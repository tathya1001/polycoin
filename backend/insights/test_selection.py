"""A click on a chart as a filter: the selection that narrows the other panels, and the list of
transactions behind a mark."""

from datetime import date
from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from categories.models import Category
from insights import services
from insights.spec import PARAMETER_DEFAULTS, SpecError, validate_selection
from transactions.tests import make_txn, make_user

pytestmark = pytest.mark.django_db

D = Decimal
ROWS = "/api/insights/rows/"
BAR = {"chart": "bar", "x": {"field": "category"}, "y": {"measure": "spend"}}
KPI = {"chart": "kpi", "y": {"measure": "spend"}}
LINE = {"chart": "line", "x": {"field": "date", "granularity": "day"}, "y": {"measure": "spend"}}
MERCHANTS = {"chart": "bar", "x": {"field": "merchant"}, "y": {"measure": "spend"}}
MARCH = {"date": {"preset": "custom", "from": "2026-03-01", "to": "2026-03-31"}}
TODAY = date(2026, 4, 1)


# --- the selection itself -------------------------------------------------------------------


def test_an_empty_selection_is_valid_and_empty():
    assert validate_selection(None) == {}
    assert validate_selection({}) == {}


def test_a_clean_selection_keeps_only_what_was_given():
    raw = {
        "categories": ["Food", " Food ", "Bills"],
        "type": "debit",
        "merchants": ["Tastybites"],
        "weekdays": [4, 1, 1],
        "months": [3],
        "date": {"from": "2026-03-01", "to": "2026-03-07"},
    }
    assert validate_selection(raw) == {
        "categories": ["Food", "Bills"],
        "type": "debit",
        "merchants": ["Tastybites"],
        "weekdays": [1, 4],
        "months": [3],
        "date": {"from": "2026-03-01", "to": "2026-03-07"},
    }


@pytest.mark.parametrize(
    "raw",
    [
        ["Food"],
        {"colour": "red"},
        {"categories": "Food"},
        {"categories": [""]},
        {"categories": [5]},
        {"categories": [f"c{i}" for i in range(21)]},
        {"merchants": ["x" * 101]},
        {"type": "transfer"},
        {"weekdays": [7]},
        {"weekdays": [True]},
        {"weekdays": ["1"]},
        {"months": [0]},
        {"months": [13]},
        {"date": {"from": "2026-03-07", "to": "2026-03-01"}},
        {"date": {"from": "2026-03-01"}},
        {"date": {"from": "yesterday", "to": "today"}},
        {"date": {"from": "2026-03-01", "to": "2026-03-02", "extra": 1}},
    ],
)
def test_an_impossible_selection_is_refused(raw):
    with pytest.raises(SpecError):
        validate_selection(raw)


# --- through the batch ----------------------------------------------------------------------


@pytest.fixture
def alice():
    user = make_user("alice@example.com")
    rows = (
        (5, "100", "Food", "debit", "Tastybites"),  # a Thursday
        (6, "30", "Bills", "debit", "Powerco"),
        (7, "20", "Health", "debit", "Wellclinic"),
        (9, "10", "Food", "debit", "TASTYBITES "),  # a Monday
        (10, "500", "Salary", "credit", "Acme Payroll"),
    )
    for day, amount, category, kind, name in rows:
        make_txn(
            user,
            date=date(2026, 3, day),
            amount=D(amount),
            txn_type=kind,
            name=name,
            description=f"d{day}",
            category=Category.objects.get(user=user, name=category),
        )
    return user


def batch(user, queries, selection=None, source=None, parameters=None):
    return services.run_queries(
        user,
        MARCH,
        queries,
        today=TODAY,
        parameters=parameters,
        selection=selection,
        selection_source=source,
    )


def figure(result):
    """The number a KPI card shows."""
    return result["rows"][0][0]


def panels():
    return [
        {"key": "bars", "spec": BAR},
        {"key": "total", "spec": KPI},
        {"key": "days", "spec": LINE},
    ]


def test_no_selection_changes_nothing(alice):
    plain = batch(alice, panels())
    assert batch(alice, panels(), selection={}, source="bars") == plain


def test_a_category_selection_narrows_every_other_panel(alice):
    results = batch(alice, panels(), {"categories": ["Food"]}, source="bars")
    assert figure(results["total"]) == "110.00"
    assert sum(D(row[1]) for row in results["days"]["rows"]) == D("110.00")


def test_the_source_panel_keeps_showing_everything(alice):
    results = batch(alice, panels(), {"categories": ["Food"]}, source="bars")
    assert {row[0] for row in results["bars"]["rows"]} == {"Food", "Bills", "Health"}


def test_a_selection_without_a_source_narrows_every_panel(alice):
    results = batch(alice, panels(), {"categories": ["Food"]})
    assert results["bars"]["rows"] == [["Food", "110.00"]]


def test_category_names_match_ignoring_case(alice):
    results = batch(alice, panels(), {"categories": ["food"]})
    assert figure(results["total"]) == "110.00"


def test_two_categories_are_either_or(alice):
    results = batch(alice, panels(), {"categories": ["Food", "Bills"]})
    assert figure(results["total"]) == "140.00"


def test_a_merchant_selection_groups_names_like_the_chart_does(alice):
    # "Tastybites" and "TASTYBITES " are one merchant on a chart, so one click covers both.
    results = batch(alice, panels(), {"merchants": ["Tastybites"]})
    assert figure(results["total"]) == "110.00"


def test_a_weekday_selection(alice):
    thursday = batch(alice, panels(), {"weekdays": [3]})
    assert figure(thursday["total"]) == "100.00"
    monday = batch(alice, panels(), {"weekdays": [0]})
    assert figure(monday["total"]) == "10.00"


def test_a_month_of_year_selection(alice):
    assert figure(batch(alice, panels(), {"months": [3]})["total"]) == "160.00"
    assert figure(batch(alice, panels(), {"months": [4]})["total"]) == "0.00"


def test_a_date_selection_narrows_the_period(alice):
    results = batch(alice, panels(), {"date": {"from": "2026-03-06", "to": "2026-03-07"}})
    assert figure(results["total"]) == "50.00"
    assert results["total"]["period"] == {"from": "2026-03-06", "to": "2026-03-07"}
    assert len(results["days"]["rows"]) == 2


def test_dates_outside_a_panels_period_leave_it_empty_not_broken(alice):
    elsewhere = {"date": {"from": "2025-01-01", "to": "2025-01-31"}}
    results = batch(alice, panels(), elsewhere)
    assert figure(results["total"]) == "0.00"
    assert "error" not in results["bars"] and results["bars"]["rows"] == []


def test_the_selection_also_applies_to_a_kpis_comparison_rows(alice):
    # Two weeks, one the clicked one: the comparison is for the same clicked category.
    make_txn(
        alice,
        date=date(2026, 2, 5),
        amount=D("40"),
        name="Tastybites",
        description="earlier",
        category=Category.objects.get(user=alice, name="Food"),
    )
    make_txn(
        alice,
        date=date(2026, 2, 6),
        amount=D("999"),
        name="Powerco",
        description="earlier bills",
        category=Category.objects.get(user=alice, name="Bills"),
    )
    kpi = {"chart": "kpi", "y": {"measure": "spend"}, "kpi": {"compare": "previous"}}
    results = batch(alice, [{"key": "k", "spec": kpi}], {"categories": ["Food"]})
    assert figure(results["k"]) == "110.00"
    assert results["k"]["rows"][0][1] == "40.00"


def test_a_panels_own_filters_still_apply_alongside_the_selection(alice):
    only_bills = {
        **BAR,
        "filters": {"categories": [str(Category.objects.get(user=alice, name="Bills").id)]},
    }
    results = batch(alice, [{"key": "b", "spec": only_bills}], {"categories": ["Food"]})
    assert results["b"]["rows"] == []  # Bills AND Food: nothing


def test_a_bad_selection_is_refused(alice):
    with pytest.raises(SpecError):
        batch(alice, panels(), {"weekdays": [9]})


def test_a_merchant_selection_works_on_a_panel_that_does_not_read_names(alice):
    results = batch(alice, [{"key": "bars", "spec": BAR}], {"merchants": ["Powerco"]})
    assert results["bars"]["rows"] == [["Bills", "30.00"]]


def test_a_text_panel_ignores_the_selection(alice):
    note = {"chart": "text", "text": "hello"}
    results = batch(alice, [{"key": "n", "spec": note}], {"categories": ["Food"]})
    assert results["n"]["meta"]["chart"] == "text"


# --- the rows behind a mark -------------------------------------------------------------------


def rows_of(user, spec, mark=None, **extra):
    return services.list_rows(user, MARCH, spec, mark, today=TODAY, **extra)


def test_the_rows_behind_a_bar_are_its_transactions_newest_first(alice):
    body = rows_of(alice, BAR, {"categories": ["Food"]})
    assert body["total"] == 2
    assert [row["date"] for row in body["rows"]] == ["2026-03-09", "2026-03-05"]
    assert body["rows"][0] == {
        "date": "2026-03-09",
        "name": "TASTYBITES ",
        "category": "Food",
        "data_source": "Main",
        "txn_type": "debit",
        "amount": "10.00",
    }


def test_the_value_agrees_with_the_chart(alice):
    body = rows_of(alice, BAR, {"categories": ["Food"]})
    chart = batch(alice, [{"key": "bars", "spec": BAR}])["bars"]["rows"]
    assert body["value"] == dict(map(tuple, chart))["Food"]


def test_a_spend_panel_lists_only_debits(alice):
    body = rows_of(alice, BAR)
    assert body["total"] == 4
    assert {row["txn_type"] for row in body["rows"]} == {"debit"}
    assert body["totals"] == {"debit": "160.00", "credit": "0.00"}


def test_an_income_panel_lists_only_credits(alice):
    income = {"chart": "bar", "x": {"field": "category"}, "y": {"measure": "income"}}
    body = rows_of(alice, income)
    assert [row["name"] for row in body["rows"]] == ["Acme Payroll"]
    assert body["value"] == "500.00"


def test_an_empty_mark_lists_everything_the_panel_counts(alice):
    assert rows_of(alice, KPI)["total"] == 4


def test_a_weekday_mark(alice):
    body = rows_of(alice, BAR, {"weekdays": [3]})
    assert [row["name"] for row in body["rows"]] == ["Tastybites"]


def test_a_date_mark_narrows_the_period(alice):
    body = rows_of(alice, LINE, {"date": {"from": "2026-03-06", "to": "2026-03-07"}})
    assert body["total"] == 2
    assert body["period"] == {"from": "2026-03-06", "to": "2026-03-07"}


def test_a_mark_outside_the_period_lists_nothing(alice):
    body = rows_of(alice, BAR, {"date": {"from": "2025-01-01", "to": "2025-01-02"}})
    assert body["total"] == 0 and body["rows"] == []


def test_the_dashboard_bar_filters_apply_to_the_list(alice):
    filters = {**MARCH, "categories": [str(Category.objects.get(user=alice, name="Bills").id)]}
    body = services.list_rows(alice, filters, BAR, None, today=TODAY)
    assert [row["category"] for row in body["rows"]] == ["Bills"]


def test_pages_are_cut_by_offset_and_limit(alice):
    first = rows_of(alice, BAR, limit=2)
    second = rows_of(alice, BAR, offset=2, limit=2)
    assert first["total"] == second["total"] == 4
    assert len(first["rows"]) == len(second["rows"]) == 2
    assert {row["date"] for row in first["rows"]}.isdisjoint(row["date"] for row in second["rows"])


def test_a_page_is_never_longer_than_the_cap(alice):
    assert len(rows_of(alice, BAR, limit=10_000)["rows"]) == 4
    assert services.ROWS_PAGE_MAX == 100


def test_a_bound_panel_lists_rows_for_the_resolved_measure(alice):
    bound = {**BAR, "bind": {"measure": "measure"}}
    body = rows_of(alice, bound, parameters={**PARAMETER_DEFAULTS, "measure": "income"})
    assert [row["txn_type"] for row in body["rows"]] == ["credit"]


def test_a_note_has_no_rows(alice):
    with pytest.raises(SpecError):
        rows_of(alice, {"chart": "text", "text": "hello"})


def test_a_bad_mark_is_refused(alice):
    with pytest.raises(SpecError):
        rows_of(alice, BAR, {"weekdays": [9]})


def test_too_many_rows_is_reported(alice, settings):
    settings.INSIGHTS_MAX_ROWS = 2
    with pytest.raises(services.TooManyRows):
        rows_of(alice, BAR)


# --- the endpoint ------------------------------------------------------------------------------


def as_user(user):
    api = APIClient()
    api.force_authenticate(user)
    return api


def test_rows_requires_login():
    assert APIClient().post(ROWS, {"spec": BAR}, format="json").status_code == 401


def test_the_endpoint_lists_the_rows(alice):
    body = {"filters": MARCH, "spec": BAR, "mark": {"categories": ["Food"]}}
    response = as_user(alice).post(ROWS, body, format="json")
    assert response.status_code == 200
    assert response.data["total"] == 2 and response.data["value"] == "110.00"


def test_the_endpoint_never_shows_another_users_rows(alice):
    bob = make_user("bob@example.com")
    response = as_user(bob).post(ROWS, {"filters": MARCH, "spec": BAR}, format="json")
    assert response.status_code == 200
    assert response.data["total"] == 0 and response.data["rows"] == []


def test_the_endpoint_answers_a_bad_spec_with_a_code(alice):
    response = as_user(alice).post(ROWS, {"spec": {"chart": "cube"}}, format="json")
    assert response.status_code == 400
    assert response.data["code"] == "invalid_spec"


def test_the_endpoint_answers_a_bad_mark_with_a_code(alice):
    response = as_user(alice).post(ROWS, {"spec": BAR, "mark": {"months": [0]}}, format="json")
    assert response.status_code == 400 and response.data["code"] == "invalid_spec"


def test_the_endpoint_answers_too_many_rows_with_a_code(alice, settings):
    settings.INSIGHTS_MAX_ROWS = 2
    response = as_user(alice).post(ROWS, {"filters": MARCH, "spec": BAR}, format="json")
    assert response.status_code == 400 and response.data["code"] == "too_many_rows"


@pytest.mark.parametrize("extra", [{"limit": 0}, {"limit": 101}, {"offset": -1}])
def test_the_endpoint_refuses_a_bad_page(alice, extra):
    response = as_user(alice).post(ROWS, {"spec": BAR, **extra}, format="json")
    assert response.status_code == 400


def test_the_endpoint_has_its_own_throttle(alice, settings):
    from rest_framework.throttling import ScopedRateThrottle

    from insights.views import RowsView

    assert RowsView.throttle_scope == "insights_rows"
    assert "insights_rows" in settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]
    assert ScopedRateThrottle in [type(t) for t in RowsView().get_throttles()]


def test_the_query_endpoint_takes_a_selection(alice):
    body = {
        "filters": MARCH,
        "selection": {"categories": ["Food"]},
        "selection_source": "bars",
        "queries": [{"key": "bars", "spec": BAR}, {"key": "total", "spec": KPI}],
    }
    response = as_user(alice).post("/api/insights/query/", body, format="json")
    assert response.status_code == 200
    assert figure(response.data["results"]["total"]) == "110.00"
    assert len(response.data["results"]["bars"]["rows"]) == 3


def test_the_query_endpoint_refuses_a_bad_selection(alice):
    body = {"selection": {"weekdays": [9]}, "queries": [{"key": "a", "spec": KPI}]}
    response = as_user(alice).post("/api/insights/query/", body, format="json")
    assert response.status_code == 400 and response.data["code"] == "invalid_spec"


# --- the list agrees with the chart it was opened from -------------------------------------------


def test_the_list_also_applies_the_click_that_is_filtering_the_dashboard(alice):
    # The bars are filtered to Thursdays by a click elsewhere; a bar's list must be too.
    thursdays = {"weekdays": [3]}
    chart = batch(alice, [{"key": "bars", "spec": BAR}], thursdays, source="other")["bars"]["rows"]
    body = services.list_rows(
        alice, MARCH, BAR, {"categories": ["Food"]}, today=TODAY, selection=thursdays
    )
    assert body["total"] == 1
    assert body["value"] == dict(map(tuple, chart))["Food"] == "100.00"


def test_a_click_filter_on_dates_narrows_the_list(alice):
    body = services.list_rows(
        alice,
        MARCH,
        BAR,
        None,
        today=TODAY,
        selection={"date": {"from": "2026-03-09", "to": "2026-03-31"}},
    )
    assert [row["date"] for row in body["rows"]] == ["2026-03-09"]
    assert body["period"] == {"from": "2026-03-09", "to": "2026-03-31"}


def test_a_click_filter_and_a_mark_that_do_not_overlap_list_nothing(alice):
    body = services.list_rows(
        alice,
        MARCH,
        LINE,
        {"date": {"from": "2026-03-05", "to": "2026-03-05"}},
        today=TODAY,
        selection={"date": {"from": "2026-03-09", "to": "2026-03-10"}},
    )
    assert body["total"] == 0 and body["rows"] == []


def test_a_bad_click_filter_on_the_list_is_refused(alice):
    with pytest.raises(SpecError):
        services.list_rows(alice, MARCH, BAR, None, today=TODAY, selection={"months": [0]})


def test_pages_never_repeat_or_skip_rows_that_tie_on_date_and_amount():
    user = make_user("carol@example.com")
    food = Category.objects.get(user=user, name="Food")
    for index in range(7):  # same day, same amount: only the id orders them
        make_txn(
            user,
            date=date(2026, 3, 5),
            amount=D("10"),
            name=f"Shop {index}",
            description=f"t{index}",
            category=food,
        )
    seen = []
    for offset in range(0, 7, 2):
        page = services.list_rows(user, MARCH, BAR, None, offset=offset, limit=2, today=TODAY)
        seen += [row["name"] for row in page["rows"]]
    assert sorted(seen) == [f"Shop {index}" for index in range(7)]
    again = services.list_rows(user, MARCH, BAR, None, limit=7, today=TODAY)
    assert [row["name"] for row in again["rows"]] == seen  # the same order every time


def test_the_list_does_not_send_internal_ids(alice):
    body = services.list_rows(alice, MARCH, BAR, None, today=TODAY)
    assert all(
        set(row) == {"date", "name", "category", "data_source", "txn_type", "amount"}
        for row in body["rows"]
    )


def test_the_endpoint_takes_the_click_filter(alice):
    body = {
        "filters": MARCH,
        "spec": BAR,
        "mark": {"categories": ["Food"]},
        "selection": {"weekdays": [3]},
    }
    response = as_user(alice).post(ROWS, body, format="json")
    assert response.status_code == 200 and response.data["total"] == 1

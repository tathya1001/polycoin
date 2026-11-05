"""The transactions list filtered on its columns, including the encrypted ones.

Filters on encrypted columns only travel in the body of POST /api/transactions/search/: a URL
lands in plain text in the hosts' request logs."""

from datetime import date
from decimal import Decimal

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from categories.testing import category_named
from datasources.services import create_source, first_source
from vault.services import UserCipher

from .tests import make_txn, make_user
from .views import SEARCH_KEYS

pytestmark = pytest.mark.django_db

D = Decimal
URL = "/api/transactions/"
SEARCH_URL = "/api/transactions/search/"


@pytest.fixture
def alice():
    return make_user("alice@example.com")


@pytest.fixture
def api(alice):
    client = APIClient()
    client.force_authenticate(alice)
    return client


def add(user, name="Tastybites", amount="10.00", balance="100.00", notes=None, **extra):
    row = make_txn(
        user,
        name=name,
        amount=D(amount),
        balance=None if balance is None else D(balance),
        description=f"{name}/{amount}/{balance}/{extra.get('date', '')}",
        **extra,
    )
    if notes:
        row.notes_enc = UserCipher(user).encrypt(notes.encode(), "txn.notes")
        row.save(update_fields=["notes_enc"])
    return row


def search(api, page=None, body=None, **filters):
    url = SEARCH_URL if page is None else f"{SEARCH_URL}?page={page}"
    return api.post(url, filters if body is None else body, format="json")


def names(api, **filters):
    return [row["name"] for row in search(api, **filters).data["results"]]


def test_name_is_matched_anywhere_in_it_ignoring_case(alice, api):
    add(alice, "Tastybites Cafe")
    add(alice, "Quick Mart")
    assert names(api, name="BITES") == ["Tastybites Cafe"]


def test_spaces_around_a_search_dont_count(alice, api):
    add(alice, "Quick Mart")
    assert names(api, name="  quick   mart ") == ["Quick Mart"]


def test_notes_are_searched_and_a_row_with_none_never_matches(alice, api):
    add(alice, "Lunch", notes="team outing")
    add(alice, "Dinner")
    assert names(api, notes="outing") == ["Lunch"]


@pytest.mark.parametrize(
    "filters, expected",
    [
        ({"amount_min": "20"}, ["Mid", "Big"]),
        ({"amount_max": "20"}, ["Small", "Mid"]),
        ({"amount_min": "15", "amount_max": "25"}, ["Mid"]),
    ],
)
def test_amount_range_includes_both_ends(alice, api, filters, expected):
    add(alice, "Small", "10.00")
    add(alice, "Mid", "20.00")
    add(alice, "Big", "30.00")
    assert sorted(names(api, **filters), key=expected.index) == expected


def test_a_balance_can_be_negative(alice, api):
    add(alice, "Overdrawn", balance="-50.00")
    add(alice, "Fine", balance="50.00")
    assert names(api, balance_max="0") == ["Overdrawn"]


def test_a_row_with_no_balance_never_matches_a_balance_filter(alice, api):
    add(alice, "None", balance=None)
    add(alice, "Some", balance="50.00")
    assert names(api, balance_min="-1000") == ["Some"]


def test_filters_combine(alice, api):
    food = category_named(alice, "Food")
    add(alice, "Tastybites Lunch", "10.00", category=food, date=date(2026, 3, 5))
    add(alice, "Tastybites Dinner", "90.00", category=food, date=date(2026, 3, 6))
    add(alice, "Tastybites Rent", "90.00", date=date(2026, 3, 6))
    add(alice, "Tastybites Old", "90.00", category=food, date=date(2025, 3, 6))
    found = names(api, name="tasty", amount_min="50", category=str(food.pk), **{"from": "2026-01-01"})
    assert found == ["Tastybites Dinner"]


def test_several_categories_can_be_chosen(alice, api):
    food = category_named(alice, "Food")
    rent = category_named(alice, "Rent")
    add(alice, "A", category=food)
    add(alice, "B", category=rent)
    add(alice, "C")
    assert sorted(names(api, category=f"{food.pk},{rent.pk}")) == ["A", "B"]


def test_one_category_still_works_for_a_link_from_a_chart(alice, api):
    food = category_named(alice, "Food")
    add(alice, "A", category=food)
    assert names(api, category=str(food.pk)) == ["A"]


def test_a_search_is_paged_and_says_the_true_total(alice, api):
    for number in range(53):
        add(alice, f"Cafe {number:02d}", date=date(2026, 1, 1))
    add(alice, "Other")

    first = search(api, name="cafe").data
    second = search(api, page=2, name="cafe").data

    assert first["count"] == 53
    assert len(first["results"]) == 50 and len(second["results"]) == 3
    assert first["next"].endswith("/api/transactions/search/?page=2")  # the terms are not in it
    seen = {row["id"] for row in first["results"]} | {row["id"] for row in second["results"]}
    assert len(seen) == 53


def test_same_day_rows_never_repeat_or_vanish_between_pages(alice, api):
    for number in range(55):
        add(alice, f"Row {number}", date=date(2026, 1, 1))
    first = search(api).data["results"]
    second = search(api, page=2).data["results"]
    assert len({row["id"] for row in [*first, *second]}) == 55


def test_a_search_never_reads_another_users_rows(alice, api):
    bob = make_user("bob@example.com")
    add(bob, "Tastybites")
    assert names(api, name="tasty") == []


def test_a_search_can_be_limited_to_a_source(alice, api):
    river = create_source(alice, UserCipher(alice), "River Bank")
    add(alice, "Cafe", data_source=first_source(alice))
    add(alice, "Cafe", amount="11.00", data_source=river)
    assert search(api, name="cafe", data_source=str(river.pk)).data["count"] == 1


def test_a_search_past_the_row_cap_is_refused_before_decrypting(alice, api, settings):
    settings.INSIGHTS_MAX_ROWS = 1
    add(alice, "A")
    add(alice, "B", amount="11.00")
    response = search(api, name="a")
    assert response.status_code == 400
    assert response.data["code"] == "too_many_rows"


def test_plain_filters_ignore_the_row_cap(alice, api, settings):
    settings.INSIGHTS_MAX_ROWS = 1
    add(alice, "A")
    add(alice, "B", amount="11.00")
    assert search(api).data["count"] == 2
    assert api.get(URL).data["count"] == 2


@pytest.mark.parametrize(
    "filters",
    [
        {"amount_min": "lots"},
        {"balance_max": "NaN"},
        {"amount_max": "Infinity"},
        {"name": "x" * 101},
        {"category": "nope"},
        {"category": ""},
        # Not text: refused before any parser sees it.
        {"amount_min": 5},
        {"name": None},
        {"category": ["a", "b"]},
        {"notes": {"$ne": ""}},
    ],
)
def test_bad_values_are_400_not_500(alice, api, filters):
    assert search(api, **filters).status_code == 400


@pytest.mark.parametrize("body", [["name", "a"], "name=a"])
def test_a_body_that_is_not_an_object_is_400(alice, api, body):
    assert search(api, body=body).status_code == 400


def test_blank_search_boxes_are_no_search(alice, api):
    add(alice, "A")
    assert search(api, name="  ", amount_min="").data["count"] == 1


def test_unknown_keys_are_ignored(alice, api):
    add(alice, "A")
    assert search(api, colour="red").data["count"] == 1


# --- the terms never travel in a URL --------------------------------------------


@pytest.mark.parametrize("key", SEARCH_KEYS)
def test_the_list_refuses_search_terms_in_the_url(alice, api, key):
    add(alice, "A")
    response = api.get(URL, {key: "1"})
    assert response.status_code == 400
    assert response.data["code"] == "use_search"


def test_the_list_still_takes_plain_filters_in_the_url(alice, api):
    food = category_named(alice, "Food")
    add(alice, "A", category=food, date=date(2026, 3, 5))
    add(alice, "B", date=date(2026, 3, 5))
    add(alice, "C", category=food, date=date(2025, 3, 5))
    response = api.get(URL, {"category": str(food.pk), "from": "2026-01-01", "type": "debit"})
    assert [row["name"] for row in response.data["results"]] == ["A"]


def test_a_search_needs_a_signed_in_user():
    assert APIClient().post(SEARCH_URL, {"name": "a"}, format="json").status_code == 401


def test_get_is_not_a_search(alice, api):
    assert api.get(SEARCH_URL).status_code == 405


def test_searches_have_their_own_rate_limit(alice, api, settings):
    rates = settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]
    assert rates["transaction_search"]
    add(alice, "A")
    original = rates["transaction_search"]
    rates["transaction_search"] = "1/hour"
    cache.clear()
    try:
        assert search(api, name="a").status_code == 200
        assert search(api, name="a").status_code == 429
        assert search(api).status_code == 200  # a search with no encrypted filter isn't limited
        assert api.get(URL).status_code == 200  # nor is the plain list
    finally:
        rates["transaction_search"] = original

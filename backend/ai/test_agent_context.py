from datetime import date

import pytest

from ai.agent.context import (
    CategoryIndex,
    CategoryRef,
    build_context,
    match_merchant,
    merchant_by_meaning,
    merchant_names,
    rag_available,
)
from ai.test_rag_retriever import DIGEST, MODEL, NEAR_GYM, NEAR_RENT
from ai.test_rag_retriever import history as indexed_history
from categories.models import Category
from transactions.tests import make_txn, make_user

TODAY = date(2026, 2, 15)
EMBED = {"model": MODEL, "digest": DIGEST}

FOOD = CategoryRef("1", "Food")
GROCERIES = CategoryRef("2", "Groceries")
TRANSPORT = CategoryRef("3", "Transport")
FUN = CategoryRef("4", "Entertainment")
INDEX = CategoryIndex(
    [FOOD, GROCERIES, TRANSPORT, FUN],
    [("food delivery", "1"), ("Cab", "3"), ("games", "4"), ("groceries", "1")],
)


# --- categories -------------------------------------------------------------------


@pytest.mark.parametrize(
    "phrase, category, how",
    [
        ("Food", FOOD, "name"),
        ("  GROCERIES ", GROCERIES, "name"),
        ("grocery", GROCERIES, "stem"),
        ("food delivery", FOOD, "keyword"),
        ("cab", TRANSPORT, "keyword"),
        ("game", FUN, "keyword"),  # the stemmed keyword
        ("Entertainmnt", FUN, "spelling"),
    ],
)
def test_a_category_is_matched_in_order(phrase, category, how):
    found = INDEX.match(phrase)
    assert (found.category, found.how) == (category, how)


def test_a_name_wins_over_another_categorys_keyword():
    # "groceries" is also a keyword of Food here; the category's own name comes first.
    assert INDEX.match("groceries").category == GROCERIES


@pytest.mark.parametrize("phrase", ["Pets", "", "   ", "fod delivery service"])
def test_no_match_is_none(phrase):
    assert INDEX.match(phrase) is None


def test_names_keep_the_users_order():
    assert INDEX.names == ["Food", "Groceries", "Transport", "Entertainment"]


# --- merchants: pure matching --------------------------------------------------------

NAMES = ["Tastybites Cafe", "Tastybites Kitchen", "Fitzone Gym", "Maple Street Homes"]


def test_part_of_a_name_covers_every_merchant_with_it():
    found = match_merchant("  TastyBites ", NAMES)
    assert (found.contains, found.how, found.matches) == ("tastybites", "name", 2)


def test_a_near_spelling_matches_the_whole_name():
    found = match_merchant("fitzone gim", NAMES)
    assert (found.contains, found.how, found.matches) == ("fitzone gym", "spelling", 1)


@pytest.mark.parametrize("phrase", ["Riverstone Books", "", "  ", "a"])  # "a" is in every name
def test_an_unknown_merchant_is_none(phrase):
    assert match_merchant(phrase, NAMES) is None


# --- the database -------------------------------------------------------------------


@pytest.fixture
def alice(db):
    return make_user("alice@example.com")


@pytest.fixture
def bob(db):
    return make_user("bob@example.com")


def test_merchant_names_are_distinct_normalised_and_newest_first(alice, bob):
    make_txn(alice, name="fitzone  GYM", date=date(2026, 1, 1))
    make_txn(alice, name="Tastybites Cafe", date=date(2026, 2, 1))
    make_txn(alice, name="FITZONE GYM", date=date(2026, 1, 20))
    make_txn(bob, name="Riverstone Books", date=date(2026, 2, 2))
    assert merchant_names(alice) == ["Tastybites Cafe", "Fitzone Gym"]


def test_merchant_names_scan_at_most_the_limit(alice, settings):
    for day in range(1, 6):
        make_txn(alice, name=f"Shop {day}", date=date(2026, 1, day))
    assert merchant_names(alice, limit=2) == ["Shop 5", "Shop 4"]
    settings.AGENT_MERCHANT_SCAN = 3
    assert len(merchant_names(alice)) == 3


def test_build_context_loads_categories_keywords_and_first_date(alice):
    make_txn(alice, date=date(2025, 6, 1))
    make_txn(alice, date=date(2026, 1, 1))
    ctx = build_context(alice, today=TODAY)
    assert set(ctx.categories.names) == set(
        Category.objects.filter(user=alice).values_list("name", flat=True)
    )
    assert ctx.categories.match("food delivery").category.name == "Food"  # a seeded keyword
    assert ctx.first_date == date(2025, 6, 1) and ctx.today == TODAY
    assert ctx.embed is None


def test_build_context_never_sees_another_users_categories(alice, bob):
    Category.objects.create(user=bob, name="Bobs Hobby")
    assert build_context(alice).categories.match("Bobs Hobby") is None


def test_merchant_names_load_once(alice, django_assert_num_queries):
    make_txn(alice, name="Tastybites Cafe")
    ctx = build_context(alice, today=TODAY)
    assert ctx.merchant_names() == ["Tastybites Cafe"]
    with django_assert_num_queries(0):
        ctx.merchant_names()


def test_the_embedding_model_is_kept_only_when_its_index_exists(alice, bob):
    assert build_context(alice, embed=EMBED).embed is None
    indexed_history(alice)
    assert rag_available(alice, MODEL, DIGEST)
    assert not rag_available(alice, MODEL, "sha256:other")
    assert not rag_available(bob, MODEL, DIGEST)
    assert build_context(alice, embed=EMBED).embed == EMBED


def test_a_merchant_is_found_by_meaning_with_a_majority_vote(alice):
    indexed_history(alice)  # two Fitzone Gym rows, one each of the others
    ctx = build_context(alice, today=TODAY, embed=EMBED)
    found = merchant_by_meaning(ctx, "workout place", NEAR_GYM)
    assert (found.contains, found.how) == ("fitzone gym", "meaning")
    assert merchant_by_meaning(ctx, "home loan", NEAR_RENT).contains == "maple street homes"


def test_meaning_needs_an_index(alice):
    indexed_history(alice)
    assert merchant_by_meaning(build_context(alice, today=TODAY), "workout", NEAR_GYM) is None


def test_a_vector_that_does_not_fit_the_index_finds_nothing(alice):
    indexed_history(alice)
    ctx = build_context(alice, today=TODAY, embed=EMBED)
    assert merchant_by_meaning(ctx, "workout", [0.5, 0.5]) is None

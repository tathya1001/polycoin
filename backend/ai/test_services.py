"""Service-layer tests for the pieces prepare_run is built from, and for apply_decisions.
prepare_run itself is tested in test_prepare.py; the scoring maths in frontend/lib/scoring.test.ts.
"""

import uuid
from datetime import date
from types import SimpleNamespace

import pytest

from ai import services
from categories.services import get_default_category
from transactions.models import Transaction
from transactions.tests import make_txn, make_user  # shared factories

pytestmark = pytest.mark.django_db


@pytest.fixture
def alice():
    return make_user("alice@example.com")


@pytest.fixture
def bob():
    return make_user("bob@example.com")


def category(user, name):
    return user.category_set.get(name=name)


# --- the credit/debit rule ---------------------------------------------------


def test_transfer_and_custom_categories_are_allowed_in_both_directions(alice):
    alice.category_set.create(name="Freelance")

    for name in ("Transfer", "Freelance"):
        for txn_type in ("debit", "credit"):
            assert services._allowed(category(alice, name), txn_type)
    assert services._allowed(category(alice, "Salary"), "credit")
    assert not services._allowed(category(alice, "Salary"), "debit")
    shouting = SimpleNamespace(name="SALARY")  # the name lookup ignores case
    assert services._allowed(shouting, "credit")
    assert not services._allowed(shouting, "debit")


def test_the_user_can_still_put_a_debit_in_salary_by_hand_through_apply(alice):
    txn = make_txn(alice, txn_type="debit")

    result = services.apply_decisions(
        alice, [{"transaction": txn.id, "category": category(alice, "Salary").id}]
    )

    assert result["applied"] == 1
    txn.refresh_from_db()
    assert txn.category == category(alice, "Salary")


# --- _load_examples ----------------------------------------------------------


def test_example_pool_is_capped_per_category_and_type_keeping_the_newest(alice, settings):
    settings.AI_MAX_EXAMPLES_PER_CATEGORY = 2
    food = category(alice, "Food")
    for day in (1, 2, 3):
        make_txn(alice, name="x", description=f"d{day}", date=date(2026, 1, day), category=food)

    groups = services._load_examples(alice, get_default_category(alice), {"debit"})

    assert {txn.date.day for txn in groups[(food.id, "debit")]} == {2, 3}


def test_example_pool_excludes_others_other_users_and_unwanted_types(alice, bob):
    food = category(alice, "Food")
    keep = make_txn(alice, name="keep", description="1", category=food)
    make_txn(alice, name="in-others", description="2")
    make_txn(alice, name="credit", description="3", category=food, txn_type="credit")
    make_txn(bob, name="bobs", description="4", category=category(bob, "Food"))

    groups = services._load_examples(alice, get_default_category(alice), {"debit"})

    assert [txn.id for rows in groups.values() for txn in rows] == [keep.id]


# --- the category label: name + the user's own keywords ----------------------


def test_label_text_is_the_name_plus_the_users_keywords_in_a_stable_order(alice):
    pets = alice.category_set.create(name="Pets")
    assert services._label_text(pets) == "Pets"  # a brand-new category: its name alone is a seed

    pets.keywords.create(term="vet")
    pets.keywords.create(term="Kibble")

    assert services._label_text(alice.category_set.get(name="Pets")) == "Pets: Kibble, vet"


# --- apply_decisions ---------------------------------------------------------


def decision(txn, cat):
    return {"transaction": txn.id, "category": cat.id}


def test_apply_moves_rows(alice):
    txn = make_txn(alice)
    before = txn.updated_at
    food = category(alice, "Food")

    result = services.apply_decisions(alice, [decision(txn, food)])

    assert result == {"applied": 1, "skipped": []}
    txn.refresh_from_db()
    assert txn.category == food
    assert txn.updated_at > before  # .update() would skip auto_now if we forgot it


def test_apply_rejects_categories_that_are_not_the_users_or_are_others(alice, bob):
    txn = make_txn(alice)
    others = get_default_category(alice)
    bad_categories = [category(bob, "Food").id, others.id, uuid.uuid4()]

    result = services.apply_decisions(
        alice, [{"transaction": txn.id, "category": cid} for cid in bad_categories]
    )

    assert result["applied"] == 0
    assert [row["reason"] for row in result["skipped"]] == ["invalid_category"] * 3
    txn.refresh_from_db()
    assert txn.category == others


def test_apply_never_touches_another_users_transaction(alice, bob):
    victim = make_txn(bob)

    result = services.apply_decisions(alice, [decision(victim, category(alice, "Food"))])

    assert result["applied"] == 0
    assert result["skipped"] == [{"transaction": str(victim.id), "reason": "not_in_others"}]
    victim.refresh_from_db()
    assert victim.category == get_default_category(bob)


def test_apply_never_overwrites_a_row_the_user_has_since_categorised(alice):
    txn = make_txn(alice)
    groceries = category(alice, "Groceries")
    Transaction.objects.filter(pk=txn.pk).update(category=groceries)  # a human got there first

    result = services.apply_decisions(alice, [decision(txn, category(alice, "Food"))])

    assert result["skipped"][0]["reason"] == "not_in_others"
    txn.refresh_from_db()
    assert txn.category == groceries


def test_apply_with_the_same_row_twice_applies_it_once(alice):
    txn = make_txn(alice)
    food = category(alice, "Food")

    result = services.apply_decisions(alice, [decision(txn, food), decision(txn, food)])

    assert result["applied"] == 1
    assert [row["reason"] for row in result["skipped"]] == ["not_in_others"]


def test_apply_reports_a_mixed_batch_row_by_row(alice, bob):
    good = make_txn(alice, name="good", description="1")
    stolen = make_txn(bob, name="stolen", description="2")
    food = category(alice, "Food")

    result = services.apply_decisions(
        alice,
        [
            decision(good, food),
            decision(stolen, food),
            {"transaction": good.id, "category": category(bob, "Food").id},
        ],
    )

    assert result["applied"] == 1
    assert result["skipped"] == [
        {"transaction": str(stolen.id), "reason": "not_in_others"},
        {"transaction": str(good.id), "reason": "invalid_category"},
    ]

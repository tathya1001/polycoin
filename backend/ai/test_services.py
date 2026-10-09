"""Service-layer tests. No network: `FakeOllama` stands in for the real client.

The fake embeds text as a one-hot vector, so every score is exactly 0.0 or 1.0 (or a value
we can work out by hand when the blend mixes two axes), and each test can say precisely
why a row got the verdict it did.
"""

import uuid
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from ai import services
from ai.client import AIError
from categories.services import get_default_category
from transactions.models import Transaction
from transactions.tests import make_txn, make_user  # shared factories

pytestmark = pytest.mark.django_db

# One axis per seed category (by label prefix) plus one "noise" axis that no label uses.
AXES = [
    "Food", "Groceries", "Transport", "Shopping", "Bills",
    "Rent", "Salary", "Transfer", "Entertainment", "Health",
]
NOISE = len(AXES)
# Narration keyword -> the category axis it lands on. Anything else lands on NOISE.
KEYWORDS = {"tastybites": "Food", "lunch": "Food", "salary": "Salary", "petrol": "Transport"}


class FakeOllama:
    def __init__(self):
        self.calls = []  # [(model, [texts])]

    def embed(self, model, texts):
        self.calls.append((model, list(texts)))
        return [self._vector(text) for text in texts]

    def list_models(self):
        return [{"name": "fake-model", "dimension": len(AXES) + 1}]

    @staticmethod
    def _vector(text):
        vector = [0.0] * (len(AXES) + 1)
        head = text.split(":", 1)[0]
        if ":" in text and head in AXES:  # a category label, e.g. "Food: restaurant, ..."
            vector[AXES.index(head)] = 1.0
            return vector
        lowered = text.lower()
        for keyword, category in KEYWORDS.items():
            if keyword in lowered:
                vector[AXES.index(category)] = 1.0
                return vector
        vector[NOISE] = 1.0
        return vector


@pytest.fixture
def alice():
    return make_user("alice@example.com")


@pytest.fixture
def bob():
    return make_user("bob@example.com")


@pytest.fixture
def ollama():
    return FakeOllama()


def category(user, name):
    return user.category_set.get(name=name)


def by_name(result):
    return {row["name"]: row for row in result["proposals"]}


def run(user, ollama):
    return services.build_proposals(user, "fake-model", ollama)


# --- build_proposals: what it proposes ---------------------------------------


def test_clear_matches_are_proposed_and_unrecognised_text_is_not(alice, ollama):
    make_txn(alice, name="TASTYBITES", description="UPI/DR/412345678901/TASTYBITES/x@y")
    make_txn(
        alice, name="ACMESOFT", description="SALARY JUNE", txn_type="credit",
        amount=Decimal("1000"),
    )
    make_txn(alice, name="Crunchy", description="zzz", amount=Decimal("7"))

    result = run(alice, ollama)
    rows = by_name(result)

    assert rows["TASTYBITES"]["category_name"] == "Food"
    assert rows["TASTYBITES"]["decision"] == "propose"
    assert rows["TASTYBITES"]["score"] == 1.0
    assert rows["ACMESOFT"]["category_name"] == "Salary"
    assert rows["ACMESOFT"]["decision"] == "propose"
    assert rows["Crunchy"]["decision"] == "below_threshold"
    assert (result["considered"], result["proposed"], result["skipped"]) == (3, 2, 1)
    assert result["capped"] is False


def test_rows_carry_everything_the_preview_table_needs(alice, ollama):
    make_txn(alice, name="TASTYBITES", description="d", amount=Decimal("450.5"))

    row = run(alice, ollama)["proposals"][0]

    assert set(row) == {
        "transaction", "date", "txn_type", "name", "amount", "category", "category_name",
        "score", "runner_up", "runner_up_name", "runner_up_score", "decision",
    }
    assert row["date"] == "2026-01-05"
    assert row["txn_type"] == "debit"
    assert row["amount"] == "450.50"  # decrypted, canonical 2dp text
    assert row["category"] == str(category(alice, "Food").id)


def test_preview_writes_nothing(alice, ollama):
    make_txn(alice, name="TASTYBITES", description="a")
    make_txn(alice, name="ACMESOFT", description="SALARY", txn_type="credit")

    def snapshot():
        return list(
            Transaction.objects.order_by("id").values_list("id", "category_id", "updated_at")
        )

    before = snapshot()
    run(alice, ollama)
    assert snapshot() == before


def test_others_is_never_proposed_or_a_runner_up(alice, ollama):
    make_txn(alice, name="TASTYBITES", description="a")
    make_txn(alice, name="Crunchy", description="b")
    default_id = str(get_default_category(alice).id)

    for row in run(alice, ollama)["proposals"]:
        assert row["category"] != default_id
        assert row["runner_up"] != default_id


def test_only_uncategorised_rows_of_this_user_are_scored(alice, bob, ollama):
    make_txn(alice, name="TASTYBITES", description="already filed", category=category(alice, "Food"))
    pending = make_txn(alice, name="TASTYBITES", description="pending")
    make_txn(bob, name="TASTYBITES", description="bobs")

    result = run(alice, ollama)

    assert [row["transaction"] for row in result["proposals"]] == [str(pending.id)]
    alice_category_ids = {str(c.id) for c in alice.category_set.all()}
    assert {row["category"] for row in result["proposals"]} <= alice_category_ids


def test_user_with_nothing_to_score_makes_no_ollama_call(alice, ollama):
    result = run(alice, ollama)

    assert result["proposals"] == []
    assert result["considered"] == 0
    assert ollama.calls == []


# --- build_proposals: the credit/debit rule -----------------------------------
# Salary and Food both match their narration exactly (score 1.0) in these tests, so the only
# thing that can stop a wrong-direction proposal is the direction rule itself.


def test_a_debit_is_never_proposed_as_salary(alice, ollama):
    make_txn(alice, name="Acme", description="SALARY JUNE", txn_type="debit")

    row = run(alice, ollama)["proposals"][0]

    assert row["category_name"] != "Salary"
    assert row["runner_up_name"] != "Salary"
    assert row["decision"] == "below_threshold"


def test_a_credit_is_never_proposed_as_food(alice, ollama):
    make_txn(alice, name="TASTYBITES", description="refund", txn_type="credit")

    row = run(alice, ollama)["proposals"][0]

    assert row["category_name"] != "Food"
    assert row["runner_up_name"] != "Food"
    assert row["decision"] == "below_threshold"


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


# --- build_proposals: the cap, batching, validation --------------------------


def test_max_run_cap_keeps_the_newest_rows_and_says_so(alice, ollama, settings):
    settings.AI_MAX_RUN = 2
    for day in (1, 2, 3):
        make_txn(alice, name=f"row-{day}", description=f"d{day}", date=date(2026, 1, day))

    result = run(alice, ollama)

    assert result["considered"] == 2
    assert result["capped"] is True
    assert {row["name"] for row in result["proposals"]} == {"row-3", "row-2"}


def test_exactly_at_the_cap_is_not_reported_as_capped(alice, ollama, settings):
    settings.AI_MAX_RUN = 2
    for day in (1, 2):
        make_txn(alice, name=f"row-{day}", description=f"d{day}", date=date(2026, 1, day))

    result = run(alice, ollama)

    assert (result["considered"], result["capped"]) == (2, False)


def test_every_distinct_text_is_embedded_once_in_one_call(alice, ollama):
    for amount in (1, 2, 3):
        make_txn(alice, name="TASTYBITES", description="same", amount=Decimal(amount))

    run(alice, ollama)

    assert len(ollama.calls) == 1
    model, texts = ollama.calls[0]
    assert model == "fake-model"
    assert len(texts) == len(set(texts))
    assert texts.count("TASTYBITES same") == 1


def test_validate_model_accepts_installed_and_rejects_anything_else(ollama):
    services.validate_model(ollama, "fake-model")  # no error

    with pytest.raises(AIError) as raised:
        services.validate_model(ollama, "../../etc/passwd")

    assert raised.value.code == "model_not_found"


# --- build_proposals: learning from the user's own labels --------------------
# AI_BLEND_FULL_AT=1 makes a single example carry the full 0.7 weight, so the Shopping
# prototype becomes normalize(0.3 * shopping_axis + 0.7 * noise_axis) and a "Crunchy" target
# scores 0.7 / sqrt(0.3**2 + 0.7**2) ~= 0.919 against it.
BLENDED_SCORE = pytest.approx(0.7 / (0.3**2 + 0.7**2) ** 0.5, abs=1e-3)


def add_crunchy_example(user, *, txn_type="debit"):
    make_txn(
        user, name="Crunchy", description="crunchy", amount=Decimal("5"),
        category=category(user, "Shopping"), txn_type=txn_type,
    )


def add_crunchy_target(user):
    make_txn(user, name="Crunchy", description="crunchy", amount=Decimal("6"))


def test_without_examples_an_unfamiliar_text_is_not_proposed(alice, ollama, settings):
    settings.AI_BLEND_FULL_AT = 1
    add_crunchy_target(alice)

    assert run(alice, ollama)["proposals"][0]["decision"] == "below_threshold"


def test_a_manual_correction_changes_the_next_proposal(alice, ollama, settings):
    settings.AI_BLEND_FULL_AT = 1
    add_crunchy_example(alice)
    add_crunchy_target(alice)

    row = run(alice, ollama)["proposals"][0]

    assert row["decision"] == "propose"
    assert row["category_name"] == "Shopping"
    assert row["score"] == BLENDED_SCORE


def test_an_approved_proposal_teaches_the_next_run_like_any_user_decision(alice, ollama, settings):
    settings.AI_BLEND_FULL_AT = 1
    first = make_txn(alice, name="Crunchy", description="crunchy", amount=Decimal("5"))
    make_txn(alice, name="Crunchy", description="crunchy", amount=Decimal("6"))
    shopping = category(alice, "Shopping")

    before = run(alice, ollama)
    assert {row["decision"] for row in before["proposals"]} == {"below_threshold"}

    services.apply_decisions(alice, [{"transaction": first.id, "category": shopping.id}])

    after = run(alice, ollama)  # the remaining row now has an example to learn from
    assert len(after["proposals"]) == 1
    assert (after["proposals"][0]["decision"], after["proposals"][0]["category_name"]) == (
        "propose",
        "Shopping",
    )


def test_credit_examples_never_shape_a_debit_prototype(alice, ollama, settings):
    settings.AI_BLEND_FULL_AT = 1
    add_crunchy_example(alice, txn_type="credit")
    add_crunchy_target(alice)  # a debit

    assert run(alice, ollama)["proposals"][0]["decision"] == "below_threshold"


def test_another_users_labels_never_influence_my_proposals(alice, bob, ollama, settings):
    settings.AI_BLEND_FULL_AT = 1
    add_crunchy_example(bob)  # bob teaches his own Shopping category
    add_crunchy_target(alice)

    assert run(alice, ollama)["proposals"][0]["decision"] == "below_threshold"


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


# --- the category label: name + the user's own keywords ----------------------


def test_label_text_is_the_name_plus_the_users_keywords_in_a_stable_order(alice):
    pets = alice.category_set.create(name="Pets")
    assert services._label_text(pets) == "Pets"  # a brand-new category: its name alone is a seed

    pets.keywords.create(term="vet")
    pets.keywords.create(term="Kibble")

    assert services._label_text(alice.category_set.get(name="Pets")) == "Pets: Kibble, vet"


def test_a_new_category_is_embedded_by_its_name_straight_away(alice, ollama):
    alice.category_set.create(name="Pets")  # no keywords yet
    make_txn(alice, name="TASTYBITES", description="a")

    run(alice, ollama)

    assert "Pets" in ollama.calls[0][1]


def test_the_users_keywords_reach_the_embedder_and_deleted_ones_do_not(alice, ollama):
    make_txn(alice, name="TASTYBITES", description="a")
    shopping = category(alice, "Shopping")
    shopping.keywords.create(term="crunchy")
    shopping.keywords.filter(term="clothes").delete()

    run(alice, ollama)

    label = next(t for t in ollama.calls[0][1] if t.startswith("Shopping:"))
    assert "crunchy" in label
    assert "clothes" not in label
    assert "electronics" in label  # untouched starter keywords stay


def test_a_renamed_category_is_labelled_with_its_new_name_and_keeps_its_keywords(alice, ollama):
    make_txn(alice, name="TASTYBITES", description="a")
    food = category(alice, "Food")
    food.name = "Eating out"
    food.save()

    run(alice, ollama)

    label = next(t for t in ollama.calls[0][1] if t.startswith("Eating out:"))
    assert "cafe" in label


def test_one_users_keywords_never_appear_in_anothers_labels(alice, bob, ollama):
    make_txn(alice, name="TASTYBITES", description="a")
    category(bob, "Shopping").keywords.create(term="bobs-secret-word")

    run(alice, ollama)

    assert not any("bobs-secret-word" in text for text in ollama.calls[0][1])


def test_listing_labels_does_not_query_per_category(alice, ollama, django_assert_max_num_queries):
    make_txn(alice, name="TASTYBITES", description="a")

    with django_assert_max_num_queries(14):  # fixed cost; was one query per category before prefetching
        run(alice, ollama)


# --- the user's notes feed the vector ----------------------------------------


def add_note(txn, text):
    from vault.services import UserCipher

    txn.notes_enc = UserCipher(txn.user).encrypt(text.encode(), "txn.notes")
    txn.save(update_fields=["notes_enc"])


def test_a_notes_text_reaches_the_embedder(alice, ollama):
    txn = make_txn(alice, name="Crunchy", description="zzz")
    add_note(txn, "dinner with Rahul")

    run(alice, ollama)

    assert "Crunchy dinner with Rahul zzz" in ollama.calls[0][1]  # name, notes, narration


def test_a_note_can_change_the_proposal(alice, ollama):
    plain = make_txn(alice, name="Crunchy", description="zzz", amount=Decimal("1"))
    noted = make_txn(alice, name="Crunchy", description="yyy", amount=Decimal("2"))
    add_note(noted, "tastybites")  # the fake model reads "tastybites" as Food

    rows = {row["transaction"]: row for row in run(alice, ollama)["proposals"]}

    assert rows[str(plain.id)]["decision"] == "below_threshold"
    assert rows[str(noted.id)]["category_name"] == "Food"
    assert rows[str(noted.id)]["decision"] == "propose"


def test_notes_on_example_rows_teach_too(alice, ollama):
    example = make_txn(alice, name="Crunchy", description="aaa", amount=Decimal("1"),
                       category=category(alice, "Shopping"))
    add_note(example, "uniquenotewords")

    make_txn(alice, name="Target", description="bbb", amount=Decimal("2"))
    run(alice, ollama)

    assert any("uniquenotewords" in text for text in ollama.calls[0][1])


def test_one_users_notes_never_reach_anothers_run(alice, bob, ollama):
    make_txn(alice, name="Crunchy", description="zzz")
    add_note(make_txn(bob, name="Crunchy", description="zzz"), "bobsprivatenote")

    run(alice, ollama)

    assert not any("bobsprivatenote" in text for text in ollama.calls[0][1])


def test_the_preview_response_does_not_expose_notes(alice, ollama):
    txn = make_txn(alice, name="Crunchy", description="zzz")
    add_note(txn, "private note text")

    result = run(alice, ollama)

    assert "private note text" not in str(result)

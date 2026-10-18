"""prepare_run tests: the texts, candidates and thresholds that the browser embeds with the
user's own Ollama and scores itself. The scoring is tested where it runs, in
frontend/lib/scoring.test.ts, against this project's original Python outputs.
"""

from datetime import date
from decimal import Decimal

import pytest

from ai import services
from transactions.models import Transaction
from transactions.tests import make_txn, make_user
from vault.services import UserCipher

pytestmark = pytest.mark.django_db


@pytest.fixture
def alice():
    return make_user("alice@example.com")


@pytest.fixture
def bob():
    return make_user("bob@example.com")


def category(user, name):
    return user.category_set.get(name=name)


def text_of(run, index):
    return run["texts"][index]


def candidate_names(run, txn_type):
    return [c["name"] for c in run["candidates"][txn_type]]


def label_of(run, name, txn_type="debit"):
    return next(text_of(run, c["label"]) for c in run["candidates"][txn_type] if c["name"] == name)


def add_note(txn, text):
    txn.notes_enc = UserCipher(txn.user).encrypt(text.encode(), "txn.notes")
    txn.save(update_fields=["notes_enc"])


# --- the response -------------------------------------------------------------


def test_a_run_has_the_documented_shape_and_the_thresholds_from_settings(alice, settings):
    settings.AI_MIN_SCORE, settings.AI_MIN_MARGIN = 0.5, 0.07
    settings.AI_BLEND_FULL_AT, settings.AI_BLEND_MAX_WEIGHT = 8, 0.6
    make_txn(alice, name="TASTYBITES", description="d", amount=Decimal("450.5"))

    run = services.prepare_run(alice)

    assert set(run) == {"considered", "capped", "thresholds", "texts", "candidates", "targets"}
    assert run["thresholds"] == {
        "min_score": 0.5, "min_margin": 0.07, "blend_full_at": 8, "blend_max_weight": 0.6,
    }
    target = run["targets"][0]
    assert set(target) == {"transaction", "date", "txn_type", "name", "amount", "text"}
    assert (target["date"], target["txn_type"], target["name"]) == ("2026-01-05", "debit", "TASTYBITES")
    assert target["amount"] == "450.50"  # decrypted, canonical 2dp text
    assert text_of(run, target["text"]) == "TASTYBITES d"


def test_every_distinct_text_appears_once_and_every_index_points_into_texts(alice):
    for amount in (1, 2, 3):
        make_txn(alice, name="TASTYBITES", description="same", amount=Decimal(amount))
    make_txn(alice, name="x", description="ex", category=category(alice, "Food"))

    run = services.prepare_run(alice)

    assert len(run["texts"]) == len(set(run["texts"]))
    assert run["texts"].count("TASTYBITES same") == 1
    used = [t["text"] for t in run["targets"]] + [
        i for cs in run["candidates"].values() for c in cs for i in [c["label"], *c["examples"]]
    ]
    assert all(0 <= i < len(run["texts"]) for i in used)


def test_candidates_follow_the_direction_rule_and_never_include_others(alice):
    alice.category_set.create(name="Freelance")
    make_txn(alice, name="a", description="1", txn_type="debit")
    make_txn(alice, name="b", description="2", txn_type="credit")

    run = services.prepare_run(alice)

    assert "Salary" not in candidate_names(run, "debit")
    assert "Food" not in candidate_names(run, "credit")
    for txn_type in ("debit", "credit"):
        assert {"Transfer", "Freelance"} <= set(candidate_names(run, txn_type))
        assert "Others" not in candidate_names(run, txn_type)


def test_only_directions_present_in_the_targets_get_candidates(alice):
    make_txn(alice, name="a", description="1", txn_type="debit")

    assert set(services.prepare_run(alice)["candidates"]) == {"debit"}


def test_labels_are_the_category_name_plus_the_users_keywords(alice):
    make_txn(alice, name="a", description="1")
    pets = alice.category_set.create(name="Pets")
    pets.keywords.create(term="vet")

    run = services.prepare_run(alice)
    labels = {c["name"]: text_of(run, c["label"]) for c in run["candidates"]["debit"]}

    assert labels["Pets"] == "Pets: vet"


def test_a_new_category_is_searchable_by_its_name_straight_away(alice):
    alice.category_set.create(name="Pets")  # no keywords yet
    make_txn(alice, name="a", description="1")

    assert label_of(services.prepare_run(alice), "Pets") == "Pets"


def test_deleted_keywords_leave_the_label_and_the_rest_stay(alice):
    make_txn(alice, name="a", description="1")
    shopping = category(alice, "Shopping")
    shopping.keywords.create(term="crunchy")
    shopping.keywords.filter(term="clothes").delete()

    label = label_of(services.prepare_run(alice), "Shopping")

    assert "crunchy" in label
    assert "clothes" not in label
    assert "electronics" in label  # untouched starter keywords stay


def test_a_renamed_category_is_labelled_with_its_new_name_and_keeps_its_keywords(alice):
    make_txn(alice, name="a", description="1")
    food = category(alice, "Food")
    food.name = "Eating out"
    food.save()

    label = label_of(services.prepare_run(alice), "Eating out")

    assert label.startswith("Eating out:")
    assert "cafe" in label


def test_only_this_users_uncategorised_rows_are_targets(alice, bob):
    make_txn(alice, name="filed", description="1", category=category(alice, "Food"))
    pending = make_txn(alice, name="pending", description="2")
    make_txn(bob, name="bobs", description="3")

    assert [t["transaction"] for t in services.prepare_run(alice)["targets"]] == [str(pending.id)]


def test_notes_on_example_rows_reach_the_texts_too(alice):
    example = make_txn(
        alice, name="Crunchy", description="aaa", amount=Decimal("1"), category=category(alice, "Shopping")
    )
    add_note(example, "uniquenotewords")
    make_txn(alice, name="Target", description="bbb", amount=Decimal("2"))

    run = services.prepare_run(alice)
    shopping = next(c for c in run["candidates"]["debit"] if c["name"] == "Shopping")

    assert any("uniquenotewords" in text_of(run, i) for i in shopping["examples"])


def test_examples_are_the_newest_per_category_and_direction(alice, settings):
    settings.AI_MAX_EXAMPLES_PER_CATEGORY = 2
    food = category(alice, "Food")
    for day in (1, 2, 3):
        make_txn(alice, name="x", description=f"d{day}", date=date(2026, 1, day), category=food)
    make_txn(alice, name="x", description="as-credit", category=food, txn_type="credit")
    make_txn(alice, name="target", description="t", date=date(2026, 2, 1))

    run = services.prepare_run(alice)
    food_debit = next(c for c in run["candidates"]["debit"] if c["name"] == "Food")

    assert sorted(text_of(run, i) for i in food_debit["examples"]) == ["x d2", "x d3"]


def test_the_cap_keeps_the_newest_rows_and_says_so(alice, settings):
    settings.AI_MAX_RUN = 2
    for day in (1, 2, 3):
        make_txn(alice, name=f"row-{day}", description=f"d{day}", date=date(2026, 1, day))

    run = services.prepare_run(alice)

    assert (run["considered"], run["capped"]) == (2, True)
    assert {t["name"] for t in run["targets"]} == {"row-3", "row-2"}


def test_nothing_to_categorise_gives_an_empty_run(alice):
    run = services.prepare_run(alice)

    assert (run["considered"], run["capped"]) == (0, False)
    assert (run["texts"], run["candidates"], run["targets"]) == ([], {}, [])


def test_another_users_rows_keywords_and_notes_never_appear(alice, bob):
    make_txn(alice, name="mine", description="m")
    make_txn(bob, name="bobs-row", description="bobs-narration")
    category(bob, "Shopping").keywords.create(term="bobs-secret-word")
    add_note(make_txn(bob, name="x", description="y", category=category(bob, "Food")), "bobs-note")

    run = services.prepare_run(alice)

    assert [t["name"] for t in run["targets"]] == ["mine"]
    alice_ids = {str(c.id) for c in alice.category_set.all()}
    assert {c["category"] for cs in run["candidates"].values() for c in cs} <= alice_ids
    for secret in ("bobs-row", "bobs-narration", "bobs-secret-word", "bobs-note"):
        assert not any(secret in text for text in run["texts"])


def test_the_users_own_notes_only_reach_the_text_to_embed(alice):
    txn = make_txn(alice, name="Crunchy", description="zzz")
    add_note(txn, "dinner with a friend")

    run = services.prepare_run(alice)

    assert text_of(run, run["targets"][0]["text"]) == "Crunchy dinner with a friend zzz"
    assert "notes" not in run["targets"][0]


def test_preparing_writes_nothing(alice):
    make_txn(alice, name="TASTYBITES", description="a")

    def snapshot():
        return list(Transaction.objects.order_by("id").values_list("id", "category_id", "updated_at"))

    before = snapshot()
    services.prepare_run(alice)
    assert snapshot() == before


def test_preparing_does_not_query_per_row_or_category(alice, django_assert_max_num_queries):
    for amount in range(1, 6):
        make_txn(alice, name=f"row-{amount}", description="d", amount=Decimal(amount))
    make_txn(alice, name="ex", description="e", category=category(alice, "Food"))

    with django_assert_max_num_queries(14):  # the same fixed cost as the preview
        services.prepare_run(alice)

import importlib

import pytest
from rest_framework.test import APIClient

from accounts.models import User
from categories.colors import CATEGORY_COLORS, OTHERS_COLOR, is_hex_color, next_color
from categories.models import Category
from categories.services import SEED_CATEGORIES, seed_default_categories

pytestmark = pytest.mark.django_db

URL = "/api/categories/"


def make_user(email):
    user = User.objects.create_user(email=email, password="x-Str0ng-pass!")
    seed_default_categories(user)
    return user


def client_for(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


@pytest.fixture
def alice():
    return make_user("alice@example.com")


@pytest.fixture
def bob():
    return make_user("bob@example.com")


# --- the palette helpers ------------------------------------------------------


def test_the_palette_is_twelve_distinct_valid_colours():
    assert len(CATEGORY_COLORS) == 12
    assert len(set(CATEGORY_COLORS)) == 12
    assert all(is_hex_color(color) for color in CATEGORY_COLORS)
    assert is_hex_color(OTHERS_COLOR)
    assert OTHERS_COLOR not in CATEGORY_COLORS


@pytest.mark.parametrize("value", ["#2A78D6", "#000000", "#ffffff".upper()])
def test_valid_hex_colours(value):
    assert is_hex_color(value)


@pytest.mark.parametrize(
    "value", ["#2a78d6", "2A78D6", "#2A78D", "#2A78D6F", "#GGGGGG", "", None, 5]
)
def test_invalid_hex_colours(value):
    assert not is_hex_color(value)


def test_next_color_skips_colours_already_in_use():
    assert next_color([]) == CATEGORY_COLORS[0]
    assert next_color([CATEGORY_COLORS[0]]) == CATEGORY_COLORS[1]
    assert next_color([CATEGORY_COLORS[1].lower()]) == CATEGORY_COLORS[0]  # case does not matter


def test_next_color_cycles_once_the_palette_is_used_up():
    assert next_color(list(CATEGORY_COLORS)) == CATEGORY_COLORS[0]
    assert next_color([*CATEGORY_COLORS, CATEGORY_COLORS[0]]) == CATEGORY_COLORS[1]


# --- seeding ------------------------------------------------------------------


def test_seeded_categories_get_distinct_colours_and_others_is_grey(alice):
    colors = {c.name: c.color for c in Category.objects.filter(user=alice)}
    assert colors["Others"] == OTHERS_COLOR
    others_removed = [color for name, color in colors.items() if name != "Others"]
    assert len(others_removed) == len(SEED_CATEGORIES) - 1
    assert len(set(others_removed)) == len(others_removed)
    assert all(is_hex_color(color) for color in colors.values())


def test_seeding_twice_does_not_change_colours(alice):
    before = dict(Category.objects.filter(user=alice).values_list("name", "color"))
    seed_default_categories(alice)
    assert dict(Category.objects.filter(user=alice).values_list("name", "color")) == before


# --- the API ------------------------------------------------------------------


def test_the_list_includes_each_categorys_colour(alice):
    rows = client_for(alice).get(URL).json()
    assert all(is_hex_color(row["color"]) for row in rows)


def test_a_new_category_gets_the_first_unused_palette_colour(alice):
    used = set(Category.objects.filter(user=alice).values_list("color", flat=True))
    expected = next(color for color in CATEGORY_COLORS if color not in used)
    res = client_for(alice).post(URL, {"name": "Gifts"}, format="json")
    assert res.status_code == 201
    assert res.json()["color"] == expected


def test_a_category_can_be_created_with_a_chosen_colour(alice):
    res = client_for(alice).post(URL, {"name": "Gifts", "color": "#ff00aa"}, format="json")
    assert res.status_code == 201
    assert res.json()["color"] == "#FF00AA"  # stored upper case


def test_patch_changes_the_colour(alice):
    food = Category.objects.get(user=alice, name="Food")
    res = client_for(alice).patch(f"{URL}{food.id}/", {"color": "#12ab34"}, format="json")
    assert res.status_code == 200
    food.refresh_from_db()
    assert food.color == "#12AB34"


def test_the_default_category_colour_can_be_changed(alice):
    others = Category.objects.get(user=alice, is_default=True)
    res = client_for(alice).patch(f"{URL}{others.id}/", {"color": "#000000"}, format="json")
    assert res.status_code == 200


@pytest.mark.parametrize("bad", ["red", "#FFF", "#GGGGGG", "FF7A1A", "#FF7A1A00", "", 12345, None])
def test_bad_colours_are_rejected(alice, bad):
    food = Category.objects.get(user=alice, name="Food")
    before = food.color
    res = client_for(alice).patch(f"{URL}{food.id}/", {"color": bad}, format="json")
    assert res.status_code == 400
    food.refresh_from_db()
    assert food.color == before


def test_renaming_keeps_the_colour(alice):
    food = Category.objects.get(user=alice, name="Food")
    before = food.color
    client_for(alice).patch(f"{URL}{food.id}/", {"name": "Dining out"}, format="json")
    food.refresh_from_db()
    assert food.color == before


def test_other_users_categories_cannot_be_recoloured(alice, bob):
    bobs = Category.objects.get(user=bob, name="Food")
    before = bobs.color
    res = client_for(alice).patch(f"{URL}{bobs.id}/", {"color": "#000000"}, format="json")
    assert res.status_code == 404
    bobs.refresh_from_db()
    assert bobs.color == before


def test_listing_still_uses_a_fixed_number_of_queries(alice, django_assert_max_num_queries):
    with django_assert_max_num_queries(6):
        client_for(alice).get(URL)


# --- the migration that backfills existing users ------------------------------


def test_the_migration_backfill_gives_each_users_categories_distinct_colours(alice, bob):
    migration = importlib.import_module("categories.migrations.0005_category_color")
    from django.apps import apps

    # Pretend the colours were never set, then run the backfill against the live models.
    Category.objects.update(color=OTHERS_COLOR)
    migration.give_existing_categories_a_colour(apps, None)

    for user in (alice, bob):
        rows = list(Category.objects.filter(user=user))
        others = [c for c in rows if c.is_default]
        rest = [c.color for c in rows if not c.is_default]
        assert [c.color for c in others] == [OTHERS_COLOR]
        assert len(set(rest)) == len(rest)
        assert all(is_hex_color(color) for color in rest)

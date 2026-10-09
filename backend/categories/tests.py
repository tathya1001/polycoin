import pytest
from rest_framework.test import APIClient

from accounts.models import User
from accounts.serializers import RegisterSerializer
from categories.models import MAX_KEYWORDS_PER_CATEGORY, Category, CategoryKeyword
from categories.services import DEFAULT_KEYWORDS, SEED_CATEGORIES, seed_default_categories

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


def test_registration_seeds_defaults():
    s = RegisterSerializer(data={"email": "new@example.com", "password": "S3cure-pass-998"})
    s.is_valid(raise_exception=True)
    user = s.save()
    cats = Category.objects.filter(user=user)
    assert set(cats.values_list("name", flat=True)) == set(SEED_CATEGORIES)
    assert cats.filter(is_default=True).get().name == "Others"


def test_seeding_is_idempotent(alice):
    seed_default_categories(alice)
    assert Category.objects.filter(user=alice).count() == len(SEED_CATEGORIES)


def test_unauthenticated_is_rejected():
    assert APIClient().get(URL).status_code == 401


def test_list_shows_only_own_categories(alice, bob):
    Category.objects.create(user=bob, name="BobOnly")
    names = {c["name"] for c in client_for(alice).get(URL).json()}
    assert "BobOnly" not in names
    assert names == set(SEED_CATEGORIES)


def test_create_attaches_the_current_user(alice):
    r = client_for(alice).post(URL, {"name": "Pets"}, format="json")
    assert r.status_code == 201
    assert Category.objects.get(id=r.json()["id"]).user == alice
    assert r.json()["is_default"] is False


def test_duplicate_name_is_rejected_case_insensitively(alice):
    r = client_for(alice).post(URL, {"name": "FOOD"}, format="json")
    assert r.status_code == 400


def test_same_name_is_fine_for_a_different_user(alice, bob):
    Category.objects.filter(user=bob, name="Food").delete()
    assert client_for(bob).post(URL, {"name": "Food"}, format="json").status_code == 201


def test_client_cannot_set_is_default(alice):
    r = client_for(alice).post(URL, {"name": "Sneaky", "is_default": True}, format="json")
    assert r.status_code == 201
    assert r.json()["is_default"] is False


def test_rename(alice):
    food = Category.objects.get(user=alice, name="Food")
    r = client_for(alice).patch(f"{URL}{food.id}/", {"name": "Eating out"}, format="json")
    assert r.status_code == 200
    food.refresh_from_db()
    assert food.name == "Eating out"


def test_rename_to_existing_name_is_rejected(alice):
    food = Category.objects.get(user=alice, name="Food")
    r = client_for(alice).patch(f"{URL}{food.id}/", {"name": "rent"}, format="json")
    assert r.status_code == 400


def test_default_cannot_be_renamed(alice):
    others = Category.objects.get(user=alice, is_default=True)
    r = client_for(alice).patch(f"{URL}{others.id}/", {"name": "Misc"}, format="json")
    assert r.status_code == 400


def test_default_cannot_be_deleted(alice):
    others = Category.objects.get(user=alice, is_default=True)
    assert client_for(alice).delete(f"{URL}{others.id}/").status_code == 400
    assert Category.objects.filter(id=others.id).exists()


def test_unused_category_can_be_deleted(alice):
    food = Category.objects.get(user=alice, name="Food")
    assert client_for(alice).delete(f"{URL}{food.id}/").status_code == 204
    assert not Category.objects.filter(id=food.id).exists()


def test_other_users_category_is_404(alice, bob):
    theirs = Category.objects.get(user=bob, name="Food")
    c = client_for(alice)
    assert c.get(f"{URL}{theirs.id}/").status_code == 404
    assert c.patch(f"{URL}{theirs.id}/", {"name": "x"}, format="json").status_code == 404
    assert c.delete(f"{URL}{theirs.id}/").status_code == 404
    theirs.refresh_from_db()
    assert theirs.name == "Food"


# --- keywords -----------------------------------------------------------------


def kw_url(category, keyword=None):
    return f"{URL}{category.id}/keywords/" + (f"{keyword.id}/" if keyword else "")


def terms(category):
    return set(category.keywords.values_list("term", flat=True))


def test_registration_seeds_the_starter_keywords_but_not_for_others():
    s = RegisterSerializer(data={"email": "kw@example.com", "password": "S3cure-pass-998"})
    s.is_valid(raise_exception=True)
    user = s.save()

    for name, expected in DEFAULT_KEYWORDS.items():
        category = Category.objects.get(user=user, name__iexact=name)
        assert terms(category) == set(expected)
    assert not Category.objects.get(user=user, is_default=True).keywords.exists()


def test_seeding_twice_does_not_duplicate_keywords(alice):
    before = CategoryKeyword.objects.filter(category__user=alice).count()
    seed_default_categories(alice)
    assert CategoryKeyword.objects.filter(category__user=alice).count() == before


def test_the_category_list_includes_each_categorys_keywords(alice):
    rows = {c["name"]: c for c in client_for(alice).get(URL).json()}

    assert {k["term"] for k in rows["Food"]["keywords"]} == set(DEFAULT_KEYWORDS["food"])
    assert rows["Others"]["keywords"] == []
    assert set(rows["Food"]["keywords"][0]) == {"id", "term"}


def test_listing_categories_uses_a_fixed_number_of_queries(alice, django_assert_max_num_queries):
    for n in range(10):
        Category.objects.create(user=alice, name=f"Extra {n}")

    with django_assert_max_num_queries(4):  # not one query per category
        client_for(alice).get(URL)


def test_add_keyword(alice):
    pets = Category.objects.create(user=alice, name="Pets")

    r = client_for(alice).post(kw_url(pets), {"term": "  Vet   clinic "}, format="json")

    assert r.status_code == 201
    assert r.json()["term"] == "Vet clinic"  # trimmed, inner spaces tidied
    assert terms(pets) == {"Vet clinic"}


@pytest.mark.parametrize(
    "term",
    ["", "   ", "x" * 61, "CAFE", "Cafe"],  # blank, too long, duplicate of a seeded term
)
def test_bad_keywords_are_rejected(alice, term):
    food = Category.objects.get(user=alice, name="Food")
    before = terms(food)

    r = client_for(alice).post(kw_url(food), {"term": term}, format="json")

    assert r.status_code == 400
    assert terms(food) == before


def test_the_category_name_cannot_be_added_as_its_own_keyword(alice):
    food = Category.objects.get(user=alice, name="Food")
    assert client_for(alice).post(kw_url(food), {"term": "food"}, format="json").status_code == 400


def test_the_default_category_cannot_have_keywords(alice):
    others = Category.objects.get(user=alice, is_default=True)
    assert client_for(alice).post(kw_url(others), {"term": "misc"}, format="json").status_code == 400


def test_a_category_has_a_keyword_limit(alice):
    pets = Category.objects.create(user=alice, name="Pets")
    CategoryKeyword.objects.bulk_create(
        [CategoryKeyword(category=pets, term=f"word{n}") for n in range(MAX_KEYWORDS_PER_CATEGORY)]
    )

    r = client_for(alice).post(kw_url(pets), {"term": "one more"}, format="json")

    assert r.status_code == 400
    assert pets.keywords.count() == MAX_KEYWORDS_PER_CATEGORY


def test_the_same_term_may_live_on_two_categories(alice):
    pets = Category.objects.create(user=alice, name="Pets")
    assert client_for(alice).post(kw_url(pets), {"term": "cafe"}, format="json").status_code == 201


def test_delete_keyword(alice):
    food = Category.objects.get(user=alice, name="Food")
    cafe = food.keywords.get(term="cafe")

    assert client_for(alice).delete(kw_url(food, cafe)).status_code == 204

    assert "cafe" not in terms(food)


def test_deleting_a_keyword_through_the_wrong_category_is_404(alice):
    food = Category.objects.get(user=alice, name="Food")
    rent = Category.objects.get(user=alice, name="Rent")
    cafe = food.keywords.get(term="cafe")

    assert client_for(alice).delete(kw_url(rent, cafe)).status_code == 404
    assert "cafe" in terms(food)


def test_other_users_keywords_cannot_be_read_added_or_deleted(alice, bob):
    theirs = Category.objects.get(user=bob, name="Food")
    keyword = theirs.keywords.get(term="cafe")
    c = client_for(alice)

    assert c.post(kw_url(theirs), {"term": "hacked"}, format="json").status_code == 404
    assert c.delete(kw_url(theirs, keyword)).status_code == 404
    assert terms(theirs) == set(DEFAULT_KEYWORDS["food"])


def test_renaming_a_category_keeps_its_keywords(alice):
    food = Category.objects.get(user=alice, name="Food")

    client_for(alice).patch(f"{URL}{food.id}/", {"name": "Eating out"}, format="json")

    assert terms(food) == set(DEFAULT_KEYWORDS["food"])


def test_deleting_a_category_deletes_its_keywords(alice):
    food = Category.objects.get(user=alice, name="Food")

    client_for(alice).delete(f"{URL}{food.id}/")

    assert not CategoryKeyword.objects.filter(category_id=food.id).exists()


def test_keyword_ids_in_urls_must_be_uuid_shaped(alice):
    food = Category.objects.get(user=alice, name="Food")
    assert client_for(alice).delete(f"{URL}{food.id}/keywords/not-a-uuid/").status_code == 404

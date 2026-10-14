import pytest
from django.contrib.auth import authenticate
from django.db.models import ProtectedError
from rest_framework.test import APIClient

from accounts.models import User, UserPreferences
from accounts.services import delete_user_data
from categories.models import Category, CategoryKeyword
from categories.services import SEED_CATEGORIES
from insights import services as insight_services
from insights.models import Dashboard, Panel
from insights.test_models import make_dashboard, make_panel
from transactions.models import Transaction
from transactions.tests import make_txn, make_user
from vault.models import UserDataKey
from vault.services import UserCipher

pytestmark = pytest.mark.django_db

URL = "/api/accounts/delete-data/"
PASSWORD = "x-Str0ng-pass!"  # what transactions.tests.make_user gives every test user


def client_for(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


def erase(user, password=PASSWORD):
    return client_for(user).post(URL, {"password": password}, format="json")


@pytest.fixture
def alice():
    return make_user("alice@example.com")


@pytest.fixture
def bob():
    return make_user("bob@example.com")


def fill(user):
    """A user with a bit of everything: transactions, a custom category with keywords, two
    dashboards with panels, and non-default preferences."""
    pets = Category.objects.create(user=user, name="Pets", color="#112233")
    CategoryKeyword.objects.create(category=pets, term="vet")
    make_txn(user)
    make_txn(user, category=pets, description="A second, different narration")
    make_panel(make_dashboard(user))
    insight_services.create_from_template(user, UserCipher(user), "Overview", "overview", 1)
    UserPreferences.objects.update_or_create(
        user=user, defaults={"font": "bitter", "chart_quality": "performance"}
    )


# --- who may call it ----------------------------------------------------------


def test_anonymous_requests_are_refused():
    res = APIClient().post(URL, {"password": PASSWORD}, format="json")
    assert res.status_code in (401, 403)


def test_get_is_not_allowed(alice):
    assert client_for(alice).get(URL).status_code == 405


# --- the password check -------------------------------------------------------


@pytest.mark.parametrize("body", [{}, {"password": ""}, {"password": None}, {"other": "x"}])
def test_a_missing_or_empty_password_is_rejected_and_nothing_is_deleted(alice, body):
    fill(alice)
    res = client_for(alice).post(URL, body, format="json")
    assert res.status_code == 400
    assert Transaction.objects.filter(user=alice).count() == 2


def test_a_wrong_password_is_rejected_and_nothing_is_deleted(alice):
    fill(alice)
    res = erase(alice, "not-the-password")
    assert res.status_code == 400
    assert res.json() == {"password": ["Incorrect password."]}
    assert Transaction.objects.filter(user=alice).count() == 2
    assert Dashboard.objects.filter(user=alice).count() == 2
    assert Category.objects.filter(user=alice, name="Pets").exists()


def test_the_password_is_not_trimmed_or_case_folded(alice):
    fill(alice)
    assert erase(alice, PASSWORD + " ").status_code == 400
    assert erase(alice, PASSWORD.upper()).status_code == 400
    assert Transaction.objects.filter(user=alice).count() == 2


def test_the_password_is_never_echoed_back(alice):
    res = erase(alice, "not-the-password")
    assert "not-the-password" not in res.content.decode()


def test_the_other_users_password_does_not_work(alice, bob):
    fill(alice)
    bob.set_password("a-completely-Different-9")
    bob.save()
    assert erase(alice, "a-completely-Different-9").status_code == 400
    assert Transaction.objects.filter(user=alice).count() == 2


# --- what is deleted ----------------------------------------------------------


def test_everything_the_user_stored_is_deleted(alice):
    fill(alice)
    res = erase(alice)
    assert res.status_code == 200
    assert not Transaction.objects.filter(user=alice).exists()
    assert not Dashboard.objects.filter(user=alice).exists()
    assert not Panel.objects.filter(dashboard__user=alice).exists()
    assert not Category.objects.filter(user=alice, name="Pets").exists()
    assert not CategoryKeyword.objects.filter(category__user=alice, term="vet").exists()


def test_the_response_counts_what_was_deleted(alice):
    fill(alice)
    categories_before = Category.objects.filter(user=alice).count()
    assert erase(alice).json() == {
        "transactions": 2,
        "dashboards": 2,
        "categories": categories_before,
    }


def test_categories_are_reset_to_the_starter_set_with_a_default(alice):
    fill(alice)
    erase(alice)
    names = sorted(Category.objects.filter(user=alice).values_list("name", flat=True))
    assert names == sorted(SEED_CATEGORIES)
    assert Category.objects.filter(user=alice, is_default=True).count() == 1
    assert CategoryKeyword.objects.filter(category__user=alice).exists()  # starter keywords too


def test_the_user_can_import_again_straight_after(alice):
    fill(alice)
    erase(alice)
    make_txn(alice)  # needs the default category and the encryption key
    assert Transaction.objects.filter(user=alice).count() == 1


def test_erasing_twice_is_fine(alice):
    fill(alice)
    erase(alice)
    res = erase(alice)
    assert res.status_code == 200
    assert res.json()["transactions"] == 0
    assert res.json()["dashboards"] == 0


def test_an_empty_account_can_be_erased(alice):
    assert erase(alice).status_code == 200


# --- what is kept -------------------------------------------------------------


def test_the_account_still_exists_and_can_still_log_in(alice):
    fill(alice)
    erase(alice)
    assert User.objects.filter(pk=alice.pk).exists()
    assert authenticate(email="alice@example.com", password=PASSWORD) is not None


def test_preferences_and_the_encryption_key_are_kept(alice):
    fill(alice)
    key_before = bytes(UserDataKey.objects.get(user=alice).wrapped_dek)
    erase(alice)
    prefs = UserPreferences.objects.get(user=alice)
    assert (prefs.font, prefs.chart_quality) == ("bitter", "performance")
    assert bytes(UserDataKey.objects.get(user=alice).wrapped_dek) == key_before


# --- other people's data ------------------------------------------------------


def test_another_users_data_is_never_touched(alice, bob):
    fill(alice)
    fill(bob)
    bobs_categories = sorted(Category.objects.filter(user=bob).values_list("id", flat=True))
    erase(alice)
    assert Transaction.objects.filter(user=bob).count() == 2
    assert Dashboard.objects.filter(user=bob).count() == 2
    assert Panel.objects.filter(dashboard__user=bob).exists()
    assert sorted(Category.objects.filter(user=bob).values_list("id", flat=True)) == bobs_categories
    assert Category.objects.filter(user=bob, name="Pets").exists()


# --- all or nothing -----------------------------------------------------------


def test_a_failure_part_way_through_deletes_nothing(alice, monkeypatch):
    fill(alice)

    def boom(user):
        raise RuntimeError("seeding failed")

    monkeypatch.setattr("accounts.services.seed_default_categories", boom)
    with pytest.raises(RuntimeError):
        delete_user_data(alice)
    # The whole thing rolled back: transactions, dashboards and the custom category survive.
    assert Transaction.objects.filter(user=alice).count() == 2
    assert Dashboard.objects.filter(user=alice).count() == 2
    assert Category.objects.filter(user=alice, name="Pets").exists()


def test_a_protected_category_gives_409_and_deletes_nothing(alice, monkeypatch):
    """If an import slips a transaction in mid-erase, Django refuses to delete the category."""
    fill(alice)

    def refuse(user):
        raise ProtectedError("protected", set())

    monkeypatch.setattr("accounts.views.delete_user_data", refuse)
    res = erase(alice)
    assert res.status_code == 409
    assert "Nothing was deleted" in res.json()["detail"]
    assert Transaction.objects.filter(user=alice).count() == 2


# --- throttling ---------------------------------------------------------------


def test_it_is_throttled_after_five_attempts_even_with_wrong_passwords(alice):
    fill(alice)
    for _ in range(5):
        assert erase(alice, "wrong-password-123").status_code == 400
    assert erase(alice, "wrong-password-123").status_code == 429
    # Once throttled even the right password is refused, so it cannot be brute-forced here.
    assert erase(alice).status_code == 429
    assert Transaction.objects.filter(user=alice).count() == 2

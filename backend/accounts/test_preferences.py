import pytest
from rest_framework.test import APIClient

from accounts.models import User, UserPreferences

ALL_FONTS = [value for value, _ in UserPreferences.FONT_CHOICES]

pytestmark = pytest.mark.django_db

URL = "/api/accounts/preferences/"


def make_user(email):
    return User.objects.create_user(email=email, password="x-Str0ng-pass!")


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


def test_anonymous_requests_are_refused():
    assert APIClient().get(URL).status_code in (401, 403)
    assert APIClient().patch(URL, {"font": "inter"}, format="json").status_code in (401, 403)


def test_the_first_read_creates_the_defaults(alice):
    assert not UserPreferences.objects.filter(user=alice).exists()
    res = client_for(alice).get(URL)
    assert res.status_code == 200
    assert res.json() == {"font": "geist", "chart_quality": "quality"}
    assert UserPreferences.objects.filter(user=alice).count() == 1


def test_reading_twice_does_not_create_a_second_row(alice):
    client = client_for(alice)
    client.get(URL)
    client.get(URL)
    assert UserPreferences.objects.filter(user=alice).count() == 1


def test_patch_changes_the_font_and_it_sticks(alice):
    client = client_for(alice)
    res = client.patch(URL, {"font": "inter"}, format="json")
    assert res.status_code == 200
    assert res.json() == {"font": "inter", "chart_quality": "quality"}
    assert client.get(URL).json() == {"font": "inter", "chart_quality": "quality"}
    assert UserPreferences.objects.get(user=alice).font == "inter"


def test_patch_works_before_anything_was_read(alice):
    res = client_for(alice).patch(URL, {"font": "inter"}, format="json")
    assert res.status_code == 200
    assert UserPreferences.objects.filter(user=alice).count() == 1


@pytest.mark.parametrize("bad", ["comic-sans", "", "INTER", None, 7, ["inter"]])
def test_unknown_fonts_are_rejected(alice, bad):
    client = client_for(alice)
    client.patch(URL, {"font": "inter"}, format="json")
    res = client.patch(URL, {"font": bad}, format="json")
    assert res.status_code == 400
    assert UserPreferences.objects.get(user=alice).font == "inter"  # unchanged


def test_unknown_fields_are_ignored_not_written(alice):
    res = client_for(alice).patch(URL, {"font": "inter", "user": 1, "id": 99}, format="json")
    assert res.status_code == 200
    assert res.json() == {"font": "inter", "chart_quality": "quality"}
    assert UserPreferences.objects.get(user=alice).user_id == alice.id


def test_put_is_not_allowed(alice):
    assert client_for(alice).put(URL, {"font": "inter"}, format="json").status_code == 405


def test_each_user_has_their_own_preferences(alice, bob):
    client_for(alice).patch(URL, {"font": "inter"}, format="json")
    assert client_for(bob).get(URL).json() == {"font": "geist", "chart_quality": "quality"}
    assert client_for(alice).get(URL).json() == {"font": "inter", "chart_quality": "quality"}


def test_deleting_a_user_deletes_their_preferences(alice):
    client_for(alice).get(URL)
    alice.delete()
    assert UserPreferences.objects.count() == 0


# --- chart quality ------------------------------------------------------------


def test_charts_default_to_high_quality(alice):
    assert client_for(alice).get(URL).json()["chart_quality"] == "quality"


def test_patch_switches_charts_to_performance_and_back(alice):
    client = client_for(alice)
    assert client.patch(URL, {"chart_quality": "performance"}, format="json").status_code == 200
    assert client.get(URL).json()["chart_quality"] == "performance"
    assert client.patch(URL, {"chart_quality": "quality"}, format="json").status_code == 200
    assert UserPreferences.objects.get(user=alice).chart_quality == "quality"


def test_changing_one_preference_leaves_the_other_alone(alice):
    client = client_for(alice)
    client.patch(URL, {"font": "inter"}, format="json")
    client.patch(URL, {"chart_quality": "performance"}, format="json")
    assert client.get(URL).json() == {"font": "inter", "chart_quality": "performance"}


@pytest.mark.parametrize("bad", ["canvas", "svg", "", "QUALITY", None, 1, ["quality"]])
def test_unknown_chart_qualities_are_rejected(alice, bad):
    client = client_for(alice)
    client.patch(URL, {"chart_quality": "performance"}, format="json")
    res = client.patch(URL, {"chart_quality": bad}, format="json")
    assert res.status_code == 400
    assert UserPreferences.objects.get(user=alice).chart_quality == "performance"  # unchanged


# --- fonts --------------------------------------------------------------------


def test_there_are_thirteen_fonts_with_unique_ids_that_fit_the_column():
    assert len(ALL_FONTS) == 13
    assert len(set(ALL_FONTS)) == 13
    assert UserPreferences.DEFAULT_FONT in ALL_FONTS
    longest = UserPreferences._meta.get_field("font").max_length
    assert all(len(font) <= longest for font in ALL_FONTS)
    # Each id becomes an HTML attribute value and a CSS selector: keep them plain.
    assert all(font == font.lower() and " " not in font for font in ALL_FONTS)


@pytest.mark.parametrize("font", ALL_FONTS)
def test_every_font_can_be_chosen_and_sticks(alice, font):
    client = client_for(alice)
    res = client.patch(URL, {"font": font}, format="json")
    assert res.status_code == 200
    assert res.json()["font"] == font
    assert client.get(URL).json()["font"] == font
    assert UserPreferences.objects.get(user=alice).font == font


@pytest.mark.parametrize(
    "bad",
    ["Space Grotesk", "space_grotesk", "SPACE-GROTESK", "comic-sans", "geist ", "'; drop"]
    + ["x" * 40],
)
def test_font_names_must_match_an_id_exactly(alice, bad):
    client = client_for(alice)
    client.patch(URL, {"font": "bitter"}, format="json")
    res = client.patch(URL, {"font": bad}, format="json")
    assert res.status_code == 400
    assert UserPreferences.objects.get(user=alice).font == "bitter"  # unchanged

"""Adults only: a date of birth at sign-up, and a gate for accounts made before it was asked."""

from datetime import date

import pytest
from django.urls import get_resolver
from rest_framework.test import APIClient

from core.tests import _api_routes
from transactions.tests import make_user
from vault.services import UserCipher, create_user_key, unlock_with_password

from . import services
from .models import User
from .services import BIRTH_DATE_CONTEXT, age_on

pytestmark = pytest.mark.django_db

REGISTER = "/api/accounts/register/"
LOGIN = "/api/accounts/login/"
BIRTH_DATE = "/api/accounts/birth-date/"
ME = "/api/accounts/me/"
PASSWORD = "S3cure-pass-998"
TODAY = date(2026, 11, 5)

# Views that answer without a date of birth on file. Keep in sync with accounts/permissions.py.
EXPECTED_EXEMPT = {
    "api/accounts/me/",
    "api/accounts/preferences/",
    "api/accounts/birth-date/",
    "api/accounts/delete-account/",
}


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    monkeypatch.setattr(services, "_today", lambda: TODAY)


def register(birth_date, email="new@example.com"):
    body = {"email": email, "password": PASSWORD}
    if birth_date is not None:
        body["birth_date"] = birth_date
    return APIClient().post(REGISTER, body, format="json")


def unconfirmed_user(email="old@example.com"):
    """An account made before dates of birth were asked for."""
    user = User.objects.create_user(email=email, password=PASSWORD)
    create_user_key(user, PASSWORD)
    return user


def client_for(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


# --- sign-up --------------------------------------------------------------------


def test_eighteen_today_can_register():
    assert register("2008-11-05").status_code == 201


def test_one_day_short_of_eighteen_cannot_register_and_no_account_is_made():
    response = register("2008-11-06")
    assert response.status_code == 400
    assert "18 or older" in str(response.data["birth_date"])
    assert not User.objects.filter(email="new@example.com").exists()


@pytest.mark.parametrize("value", [None, "", "05/11/1990", "1990-13-01", "not a date"])
def test_a_missing_or_malformed_date_is_refused(value):
    response = register(value)
    assert response.status_code == 400
    assert "birth_date" in response.data


@pytest.mark.parametrize("value", ["2026-11-06", "2030-01-01", "1899-12-31"])
def test_a_future_or_impossible_date_is_refused(value):
    response = register(value)
    assert response.status_code == 400
    assert "real date of birth" in str(response.data["birth_date"])


def test_the_date_is_stored_encrypted_and_never_sent_back():
    response = register("1990-06-15")
    assert "birth_date" not in response.data

    user = User.objects.get(email="new@example.com")
    unlock_with_password(user, PASSWORD)  # the sign-up request unlocked it, then forgot it
    blob = bytes(user.birth_date_enc)
    assert b"1990" not in blob
    assert UserCipher(user).decrypt(blob, BIRTH_DATE_CONTEXT) == b"1990-06-15"

    me = client_for(user).get(ME).data
    assert me["birth_date_required"] is False
    assert "1990" not in str(me)


@pytest.mark.parametrize(
    "born, today, age",
    [
        (date(2000, 2, 29), date(2018, 2, 28), 17),  # no 29 February that year
        (date(2000, 2, 29), date(2018, 3, 1), 18),
        (date(2000, 2, 29), date(2020, 2, 29), 20),
        (date(2000, 6, 15), date(2018, 6, 14), 17),
        (date(2000, 6, 15), date(2018, 6, 15), 18),
    ],
)
def test_age_counts_whole_years(born, today, age):
    assert age_on(born, today) == age


# --- the gate for older accounts ---------------------------------------------------


def test_an_account_without_a_date_can_do_nothing_else():
    response = client_for(unconfirmed_user()).get("/api/categories/")
    assert response.status_code == 403
    assert response.data["code"] == "birth_date_required"


def test_it_can_still_sign_in_see_who_it_is_and_load_its_look():
    user = unconfirmed_user()
    client = APIClient()
    assert client.post(LOGIN, {"email": user.email, "password": PASSWORD}, format="json").status_code == 200
    assert client.get(ME).data["birth_date_required"] is True
    assert client.get("/api/accounts/preferences/").status_code == 200


def test_giving_an_adult_date_opens_everything():
    user = unconfirmed_user()
    client = client_for(user)
    assert client.post(BIRTH_DATE, {"birth_date": "1990-06-15"}, format="json").status_code == 204
    user.refresh_from_db()
    assert UserCipher(user).decrypt(bytes(user.birth_date_enc), BIRTH_DATE_CONTEXT) == b"1990-06-15"
    assert client.get("/api/categories/").status_code == 200
    assert client.get(ME).data["birth_date_required"] is False


def test_an_under_eighteen_date_is_refused_and_the_gate_stays():
    user = unconfirmed_user()
    client = client_for(user)
    response = client.post(BIRTH_DATE, {"birth_date": "2010-01-01"}, format="json")
    assert response.status_code == 400
    user.refresh_from_db()
    assert user.birth_date_enc is None
    assert client.get("/api/categories/").status_code == 403


def test_the_date_can_only_be_given_once():
    client = client_for(make_user("alice@example.com"))  # already has one
    response = client.post(BIRTH_DATE, {"birth_date": "1980-01-01"}, format="json")
    assert response.status_code == 409


def test_giving_a_date_needs_a_signed_in_user():
    response = APIClient().post(BIRTH_DATE, {"birth_date": "1990-06-15"}, format="json")
    assert response.status_code == 401


def test_anonymous_requests_still_get_401_not_the_gate():
    assert APIClient().get("/api/categories/").status_code == 401


def test_only_the_expected_views_skip_the_gate():
    routes = list(_api_routes(get_resolver().url_patterns))
    exempt = {route for route, view in routes if getattr(view, "age_check_exempt", False)}
    assert exempt == EXPECTED_EXEMPT

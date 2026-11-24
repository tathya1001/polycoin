"""Sign-up needs a ticked Privacy Policy box, and the account records which policy it accepted."""

from datetime import date

import pytest
from django.conf import settings
from django.utils import timezone
from rest_framework.test import APIClient

from .models import User
from .serializers import MUST_ACCEPT_POLICY

pytestmark = pytest.mark.django_db

REGISTER = "/api/accounts/register/"
EMAIL = "new@example.com"
BODY = {"email": EMAIL, "password": "x-Str0ng-pass!", "birth_date": "1990-06-15"}


def register(**extra):
    return APIClient().post(REGISTER, {**BODY, **extra}, format="json")


@pytest.mark.parametrize(
    "extra", [{}, {"accept_privacy_policy": False}], ids=["missing", "unticked"]
)
def test_sign_up_without_accepting_is_refused(extra):
    response = register(**extra)

    assert response.status_code == 400
    assert response.json()["accept_privacy_policy"] == [MUST_ACCEPT_POLICY]
    assert not User.objects.filter(email=EMAIL).exists()


def test_sign_up_with_a_value_that_is_not_a_yes_or_no_is_refused():
    response = register(accept_privacy_policy="maybe")

    assert response.status_code == 400
    assert "accept_privacy_policy" in response.json()
    assert not User.objects.filter(email=EMAIL).exists()


def test_sign_up_records_the_accepted_version_and_time():
    before = timezone.now()
    response = register(accept_privacy_policy=True)
    after = timezone.now()

    assert response.status_code == 201
    assert "accept_privacy_policy" not in response.json()
    user = User.objects.get(email=EMAIL)
    assert user.privacy_policy_version == settings.PRIVACY_POLICY_VERSION
    assert before <= user.privacy_policy_accepted_at <= after


def test_accounts_made_outside_sign_up_have_no_consent_record():
    user = User.objects.create_user(email="old@example.com", password="x-Str0ng-pass!")

    assert user.privacy_policy_version == ""
    assert user.privacy_policy_accepted_at is None


def test_the_policy_version_is_its_date():
    # The version is shown as the policy's "last updated" date, so it must be a real date.
    date.fromisoformat(settings.PRIVACY_POLICY_VERSION)

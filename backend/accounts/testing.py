"""Helpers for tests in any app."""

from datetime import date

from .services import set_birth_date

ADULT_BIRTH_DATE = date(1990, 6, 15)


def confirm_age(user):
    """Give a test user a date of birth, as every account made through sign-up has. Without one,
    accounts.permissions.AgeConfirmed refuses nearly every endpoint. Needs the user's key."""
    set_birth_date(user, ADULT_BIRTH_DATE)
    return user

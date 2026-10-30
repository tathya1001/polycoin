"""Filtering the transactions list on encrypted columns.

SQL can't compare ciphertext, so these filters decrypt the rows that the plain filters leave and
test them here. The same rule the charts follow applies: count first, refuse past the row cap, and
decrypt only the columns being asked about.
"""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from django.conf import settings
from rest_framework.exceptions import ValidationError

from .links import TooManyRows

MAX_SEARCH_LENGTH = 100
_RANGES = ("amount_min", "amount_max", "balance_min", "balance_max")


@dataclass(frozen=True, slots=True)
class Search:
    name: str = ""  # case-folded
    notes: str = ""
    amount_min: Decimal | None = None
    amount_max: Decimal | None = None
    balance_min: Decimal | None = None
    balance_max: Decimal | None = None

    @property
    def reads_amount(self) -> bool:
        return self.amount_min is not None or self.amount_max is not None

    @property
    def reads_balance(self) -> bool:
        return self.balance_min is not None or self.balance_max is not None


def _number(params, key: str) -> Decimal | None:
    raw = params.get(key, "").strip()
    if not raw:
        return None
    try:
        value = Decimal(raw)
    except InvalidOperation:
        raise ValidationError({key: "Must be a number."}) from None
    if not value.is_finite():
        raise ValidationError({key: "Must be a number."})
    return value


def _text(params, key: str) -> str:
    value = " ".join(params.get(key, "").split())
    if len(value) > MAX_SEARCH_LENGTH:
        raise ValidationError({key: f"Use at most {MAX_SEARCH_LENGTH} characters."})
    return value.casefold()


def parse_search(params) -> Search | None:
    """The encrypted-column filters in the query string, or None if there are none."""
    search = Search(
        name=_text(params, "name"),
        notes=_text(params, "notes"),
        **{key: _number(params, key) for key in _RANGES},
    )
    return None if search == Search() else search


def _within(value: Decimal, low: Decimal | None, high: Decimal | None) -> bool:
    return (low is None or value >= low) and (high is None or value <= high)


def matching_ids(queryset, cipher, search: Search) -> list:
    """The ids in `queryset` that pass `search`, in the queryset's order.

    Each test runs only if the one before passed, numbers first: they are the cheapest to rule a
    row out with. Raises TooManyRows before anything is decrypted.
    """
    if queryset.count() > settings.INSIGHTS_MAX_ROWS:
        raise TooManyRows

    def dec(blob, context) -> str:
        return cipher.decrypt(bytes(blob), context).decode()

    columns = ["pk"]
    columns += ["amount_enc"] if search.reads_amount else []
    columns += ["balance_enc"] if search.reads_balance else []
    columns += ["name_enc"] if search.name else []
    columns += ["notes_enc"] if search.notes else []

    found = []
    for pk, *blobs in queryset.values_list(*columns):
        if search.reads_amount:
            amount = Decimal(dec(blobs.pop(0), "txn.amount"))
            if not _within(amount, search.amount_min, search.amount_max):
                continue
        if search.reads_balance:
            blob = blobs.pop(0)
            if blob is None:  # the statement had no balance: nothing to compare
                continue
            balance = Decimal(dec(blob, "txn.balance"))
            if not _within(balance, search.balance_min, search.balance_max):
                continue
        if search.name and search.name not in dec(blobs.pop(0), "txn.name").casefold():
            continue
        if search.notes:
            blob = blobs.pop(0)
            if blob is None or search.notes not in dec(blob, "txn.notes").casefold():
                continue
        found.append(pk)
    return found

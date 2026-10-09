from datetime import date as date_type
from decimal import Decimal

from .models import Transaction


def _money(value: Decimal) -> str:
    """One canonical text form: Decimal("4.5"), Decimal("4.50") and Decimal("4.500")
    must all become "4.50", or the same transaction would get different fingerprints."""
    return f"{value:.2f}"


def create_transaction(
    cipher,
    user,
    *,
    date: date_type,
    txn_type: str,
    name: str,
    description: str,
    amount: Decimal,
    balance: Decimal | None,
    category,
) -> Transaction:
    """The ONLY write path for transactions (the importer and the tests both use it).
    `cipher` is a vault.services.UserCipher built once per request/import."""
    if amount <= 0:
        # The sign lives in txn_type, so the stored amount is always positive.
        raise ValueError("amount must be positive; use txn_type for credit/debit.")

    amount_text = _money(amount)
    balance_text = _money(balance) if balance is not None else None

    # Everything that makes two transactions "the same" goes into the fingerprint.
    # Including the balance keeps two identical coffees on the same day distinct.
    fingerprint_source = "|".join(
        [date.isoformat(), txn_type, amount_text, balance_text or "", description]
    )

    return Transaction.objects.create(
        user=user,
        date=date,
        txn_type=txn_type,
        category=category,
        # A different context string per field: the context is bound into the
        # ciphertext, so a name blob can't be pasted into the description column.
        name_enc=cipher.encrypt(name.encode(), "txn.name"),
        description_enc=cipher.encrypt(description.encode(), "txn.description"),
        amount_enc=cipher.encrypt(amount_text.encode(), "txn.amount"),
        balance_enc=(
            cipher.encrypt(balance_text.encode(), "txn.balance")
            if balance_text is not None
            else None
        ),
        fingerprint=cipher.blind_index(fingerprint_source.encode(), "txn.fp"),
    )

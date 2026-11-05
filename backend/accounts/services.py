import logging
from datetime import date

from django.db import transaction
from django.utils import timezone
from rest_framework_simplejwt.token_blacklist.models import OutstandingToken

from categories.models import Category
from categories.services import seed_default_categories
from datasources.models import DataSource
from datasources.services import seed_default_source
from insights.models import Dashboard
from transactions.models import Transaction
from vault.services import UserCipher

logger = logging.getLogger(__name__)

MIN_AGE = 18
OLDEST_BIRTH_DATE = date(1900, 1, 1)
BIRTH_DATE_CONTEXT = "user.birth_date"


def _today() -> date:
    # UTC. A day either way does not matter for an 18+ check; tests replace this.
    return timezone.now().date()


def age_on(birth_date: date, today: date) -> int:
    """Whole years from `birth_date` to `today`. A 29 February birthday counts from 1 March in
    years that have no 29 February."""
    before_birthday = (today.month, today.day) < (birth_date.month, birth_date.day)
    return today.year - birth_date.year - before_birthday


def birth_date_problem(birth_date: date) -> str | None:
    """Why `birth_date` can't be accepted, or None if it can."""
    today = _today()
    if birth_date > today or birth_date < OLDEST_BIRTH_DATE:
        return "Enter your real date of birth."
    if age_on(birth_date, today) < MIN_AGE:
        return f"You must be {MIN_AGE} or older to use MoneyAngle."
    return None


def set_birth_date(user, birth_date: date) -> None:
    """Store an already-checked date of birth, encrypted with the user's key."""
    plaintext = birth_date.isoformat().encode()
    user.birth_date_enc = UserCipher(user).encrypt(plaintext, BIRTH_DATE_CONTEXT)
    user.save(update_fields=["birth_date_enc"])


@transaction.atomic
def delete_account(user) -> None:
    """Delete the account and everything it has. Nothing of it is left in the database.

    Most rows go by CASCADE from the user: categories and keywords, data sources, dashboards and
    panels, Ask documents, transfer links, preferences, and the encryption key. Deleting the key
    also makes every backup file the user downloaded impossible to open, on purpose.

    Two things need doing by hand first:
    - transactions, because Transaction.category and Transaction.data_source are PROTECT;
    - the JWT records (simplejwt's OutstandingToken is SET_NULL, which would keep them, and each
      holds a token naming the user). Their blacklist rows cascade.

    accounts/test_delete_account.py checks that every table returns to what it held before.
    """
    Transaction.objects.filter(user=user).delete()
    OutstandingToken.objects.filter(user=user).delete()
    user.delete()
    logger.info("an account was deleted")  # nothing that could identify it


@transaction.atomic
def delete_user_data(user) -> dict:
    """Erase everything the user has stored, but keep the account itself.

    Deleted: every transaction, every dashboard and its panels, every category and its
    keywords, every data source. The starter categories (with "Others") and a first data source
    are then created again, because the app needs them before anything can be imported.

    Kept on purpose: the account and its password, the user's encryption key (it protects
    nothing now, but the next import needs it), and the Settings preferences (they are
    settings, not data).

    All or nothing: one transaction, so a failure never leaves a half-erased account. Order
    matters: transactions go first because Transaction.category and Transaction.data_source are
    on_delete=PROTECT. Returns how many rows of each kind went, for the confirmation message.
    """
    # delete() counts cascaded rows too, so read the transactions from its per-model result.
    _, per_model = Transaction.objects.filter(user=user).delete()
    transactions = per_model.get(Transaction._meta.label, 0)
    dashboards = Dashboard.objects.filter(user=user).count()
    Dashboard.objects.filter(user=user).delete()  # its panels go with it (CASCADE)
    categories = Category.objects.filter(user=user).count()
    Category.objects.filter(user=user).delete()  # its keywords go with it (CASCADE)
    DataSource.objects.filter(user=user).delete()
    seed_default_categories(user)
    seed_default_source(user)

    # Counts only: never log what the data was.
    logger.info(
        "user %s erased their data: %s transactions, %s dashboards, %s categories",
        user.pk,
        transactions,
        dashboards,
        categories,
    )
    return {"transactions": transactions, "dashboards": dashboards, "categories": categories}

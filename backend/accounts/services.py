import logging

from django.db import transaction

from categories.models import Category
from categories.services import seed_default_categories
from insights.models import Dashboard
from transactions.models import Transaction

logger = logging.getLogger(__name__)


@transaction.atomic
def delete_user_data(user) -> dict:
    """Erase everything the user has stored, but keep the account itself.

    Deleted: every transaction, every dashboard and its panels, every category and its
    keywords. The starter categories (with "Others") are then created again, because the
    app needs a default category before anything can be imported.

    Kept on purpose: the account and its password, the user's encryption key (it protects
    nothing now, but the next import needs it), and the Settings preferences (they are
    settings, not data).

    All or nothing: one transaction, so a failure never leaves a half-erased account. Order
    matters: transactions go first because Transaction.category is on_delete=PROTECT.
    Returns how many rows of each kind went, for the confirmation message.
    """
    transactions, _ = Transaction.objects.filter(user=user).delete()
    dashboards = Dashboard.objects.filter(user=user).count()
    Dashboard.objects.filter(user=user).delete()  # its panels go with it (CASCADE)
    categories = Category.objects.filter(user=user).count()
    Category.objects.filter(user=user).delete()  # its keywords go with it (CASCADE)
    seed_default_categories(user)

    # Counts only: never log what the data was.
    logger.info(
        "user %s erased their data: %s transactions, %s dashboards, %s categories",
        user.pk,
        transactions,
        dashboards,
        categories,
    )
    return {"transactions": transactions, "dashboards": dashboards, "categories": categories}

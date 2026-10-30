import logging

from django.db import transaction

from categories.models import Category
from categories.services import seed_default_categories
from datasources.models import DataSource
from datasources.services import seed_default_source
from insights.models import Dashboard
from transactions.models import Transaction

logger = logging.getLogger(__name__)


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

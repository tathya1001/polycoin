from django.db import migrations

# Frozen copy on purpose: migrations must not change if the model's default later does.
FIRST_COLOR = "#2A78D6"


def backfill(apps, schema_editor):
    """Gives every user a first source, and puts their rows that have none into it.

    Safe to run again. This uses no keys: migrations run without the production ones, so the
    source starts with no name (see DataSource). update() leaves updated_at alone, because the
    Ask index would otherwise treat every row as changed and embed it all again.
    """
    User = apps.get_model("accounts", "User")
    DataSource = apps.get_model("datasources", "DataSource")
    Transaction = apps.get_model("transactions", "Transaction")

    have = set(DataSource.objects.values_list("user_id", flat=True))
    DataSource.objects.bulk_create(
        [
            DataSource(user_id=user_id, color=FIRST_COLOR)
            for user_id in User.objects.values_list("id", flat=True)
            if user_id not in have
        ],
    )

    first = {}
    for user_id, source_id in DataSource.objects.order_by(
        "user_id", "position", "created_at"
    ).values_list("user_id", "id"):
        first.setdefault(user_id, source_id)

    waiting = Transaction.objects.filter(data_source__isnull=True)
    for user_id in waiting.order_by().values_list("user_id", flat=True).distinct():
        waiting.filter(user_id=user_id).update(data_source_id=first[user_id])


class Migration(migrations.Migration):
    """Data only. On Postgres an ALTER TABLE after this UPDATE, in the same transaction, fails
    with "pending trigger events", so schema changes stay in their own migrations."""

    dependencies = [
        ("accounts", "0001_initial"),
        ("datasources", "0001_initial"),
        ("transactions", "0005_transaction_data_source"),
    ]

    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]

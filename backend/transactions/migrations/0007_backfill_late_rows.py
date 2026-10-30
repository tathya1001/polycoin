from importlib import import_module

from django.db import migrations


def backfill(apps, schema_editor):
    """The rows and users that the previous release's code added before it stopped serving."""
    earlier = import_module("transactions.migrations.0006_backfill_data_source")
    earlier.backfill(apps, schema_editor)


class Migration(migrations.Migration):
    """Data only, for the same reason as 0006: the ALTER TABLE gets its own migration."""

    dependencies = [
        ("transactions", "0006_backfill_data_source"),
    ]

    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]

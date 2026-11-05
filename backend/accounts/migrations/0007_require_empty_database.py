from django.db import migrations


def require_empty_database(apps, schema_editor):
    """Phase 12.2 encrypts every field of a user's data: a transaction's date, type, category and
    source, and category names and keywords. A migration has no user's key, so it can't convert
    existing rows (D17 in dev-docs/phase-12.2-security-plan.md). The database must start empty."""
    User = apps.get_model("accounts", "User")
    if User.objects.exists():
        raise RuntimeError(
            "This release needs an empty database: it can't encrypt existing data without each "
            "user's password. Start the database afresh (see the Phase 12.2 plan), then migrate."
        )


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0006_user_birth_date"),
    ]

    operations = [migrations.RunPython(require_empty_database, migrations.RunPython.noop)]

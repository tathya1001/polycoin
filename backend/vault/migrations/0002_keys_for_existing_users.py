from django.db import migrations


def check_no_user_lacks_a_key(apps, schema_editor):
    """This migration used to give a master-locked data key to users registered before the vault
    existed. Every database that had such users ran it long ago, and a fresh database has none.

    Since Phase 12.1 a key is locked with its user's password (D18 in
    dev-docs/phase-12.1-password-key-plan.md), which a migration doesn't have. So this now only
    checks, and stops with a clear message instead of guessing."""
    User = apps.get_model("accounts", "User")
    missing = User.objects.filter(data_key__isnull=True).count()
    if missing:
        raise RuntimeError(
            f"{missing} user(s) have no data key, and one can't be made without their password. "
            "Delete those accounts, or have them sign up again."
        )


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0001_initial"),
        ("vault", "0001_initial"),
    ]

    operations = [migrations.RunPython(check_no_user_lacks_a_key, migrations.RunPython.noop)]

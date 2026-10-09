import os

from django.conf import settings
from django.db import migrations


def create_missing_keys(apps, schema_editor):
    """Users registered before the vault existed have no data key, so any encrypted
    write (like an import) crashed with UserDataKey.DoesNotExist."""
    # Imported here, not at module top: it is the one place that knows the wrapping
    # format (AAD etc.), so reusing it beats a copy that could silently drift.
    from vault.services import _wrap_dek

    User = apps.get_model("accounts", "User")
    UserDataKey = apps.get_model("vault", "UserDataKey")
    version = settings.FIELD_ENCRYPTION_ACTIVE_KEY

    for user in User.objects.filter(data_key__isnull=True):
        UserDataKey.objects.create(
            user=user,
            wrapped_dek=_wrap_dek(user, os.urandom(32), version),  # only needs user.id
            kek_version=version,
        )


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0001_initial"),
        ("vault", "0001_initial"),
    ]

    operations = [migrations.RunPython(create_missing_keys, migrations.RunPython.noop)]

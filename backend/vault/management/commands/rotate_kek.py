from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from vault.models import UserDataKey
from vault.services import rewrap_user_key


class Command(BaseCommand):
    help = (
        "Re-wrap every user's data key under the active KEK "
        "(FIELD_ENCRYPTION_ACTIVE_KEY). User data is not re-encrypted."
    )

    def handle(self, *args, **options):
        rotated = skipped = 0
        # All-or-nothing: a crash must not leave keys split across KEK versions.
        with transaction.atomic():
            for record in UserDataKey.objects.select_related("user").iterator():
                if rewrap_user_key(record):
                    rotated += 1
                else:
                    skipped += 1
        self.stdout.write(
            self.style.SUCCESS(
                f"Re-wrapped {rotated} key(s) under "
                f"{settings.FIELD_ENCRYPTION_ACTIVE_KEY}; {skipped} already current."
            )
        )

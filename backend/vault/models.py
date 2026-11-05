import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q


class UserDataKey(models.Model):
    """One row per user: their random data key (DEK), never stored in a form that opens on its own.

    It is stored locked twice, and neither unlocking key is stored (Phase 12.1, D1-D3):
    - with a key derived from the user's password: Argon2id(password, password_salt), using the
      settings in `kdf_params`;
    - with the user's recovery key, which they were shown once.

    Accounts made before Phase 12.1 had it locked with a master key from the environment instead
    (`wrapped_dek` + `kek_version`). Their next login re-locks it and erases that copy (D8).
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="data_key"
    )
    password_wrapped_dek = models.BinaryField(null=True)
    password_salt = models.BinaryField(null=True)
    kdf_params = models.CharField(max_length=64, blank=True)  # e.g. "argon2id:t=3,m=65536,p=4"
    recovery_wrapped_dek = models.BinaryField(null=True)
    # Legacy, before Phase 12.1: locked with FIELD_ENCRYPTION_KEYS[kek_version]. NULL once re-locked.
    wrapped_dek = models.BinaryField(null=True)
    kek_version = models.CharField(max_length=16, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            # A key that nothing can open would lose the user's data for good.
            models.CheckConstraint(
                condition=Q(password_wrapped_dek__isnull=False) | Q(wrapped_dek__isnull=False),
                name="data_key_has_a_lock",
            ),
        ]


class VaultSession(models.Model):
    """One signed-in browser's copy of a user's data key (Phase 12.1, D4).

    The key is locked with a random secret that only that browser holds (the httpOnly "vault"
    cookie, "<id>.<secret>"). This row alone opens nothing, and logging out deletes it.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="vault_sessions"
    )
    wrapped_dek = models.BinaryField()
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

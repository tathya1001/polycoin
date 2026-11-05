import uuid

from django.conf import settings
from django.db import models


class UserDataKey(models.Model):
    """One row per user: their random data key (DEK), never stored in a form that opens on its own.

    It is stored locked twice, and neither unlocking key is stored (Phase 12.1, D1-D3):
    - with a key derived from the user's password: Argon2id(password, password_salt), using the
      settings in `kdf_params`;
    - with the user's recovery key, which they were shown once.

    There is no master key (Phase 12.2, D18): nothing on the server can open this alone.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="data_key"
    )
    password_wrapped_dek = models.BinaryField()
    password_salt = models.BinaryField()
    kdf_params = models.CharField(max_length=64)  # e.g. "argon2id:t=3,m=65536,p=4"
    recovery_wrapped_dek = models.BinaryField()
    created_at = models.DateTimeField(auto_now_add=True)


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
    expires_at = models.DateTimeField(db_index=True)  # every login purges the expired ones
    created_at = models.DateTimeField(auto_now_add=True)

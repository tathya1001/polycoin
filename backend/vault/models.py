from django.db import models
from django.conf import settings

class UserDataKey(models.Model):
    """One row per user: their random data key (DEK), stored wrapped by a master key."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="data_key"
    )
    wrapped_dek = models.BinaryField()
    kek_version = models.CharField(max_length=16)
    created_at = models.DateTimeField(auto_now_add=True)

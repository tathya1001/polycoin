from django.db import models
from core.models import OwnedModel

class Transaction(OwnedModel):
    class Type(models.TextChoices):
        CREDIT = "credit"
        DEBIT = "debit"

    date = models.DateField()
    txn_type = models.CharField(max_length=6, choices=Type.choices)
    category = models.ForeignKey("categories.Category", on_delete=models.PROTECT)
    name_enc = models.BinaryField()
    description_enc = models.BinaryField()
    amount_enc = models.BinaryField()
    balance_enc = models.BinaryField(null=True)
    # The user's own optional note. NULL means "no note" (not an encrypted empty string).
    # Not part of `fingerprint`: editing a note must never affect re-import dedupe.
    notes_enc = models.BinaryField(null=True)
    fingerprint = models.BinaryField(max_length=32)

    class Meta:
        ordering = ["-date"]
        constraints = [models.UniqueConstraint(fields=["user", "fingerprint"], name="uniq_txn_fingerprint_per_user")]
        indexes = [models.Index(fields=["user", "date"])]

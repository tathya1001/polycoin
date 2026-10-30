from django.db import models
from django.db.models import F, Q

from core.models import OwnedModel


class Transaction(OwnedModel):
    class Type(models.TextChoices):
        CREDIT = "credit"
        DEBIT = "debit"

    # No index of its own: the constraint and the index below both start with it.
    data_source = models.ForeignKey(
        "datasources.DataSource",
        on_delete=models.PROTECT,
        related_name="transactions",
        db_index=False,
    )
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
        constraints = [
            models.UniqueConstraint(
                fields=["data_source", "fingerprint"], name="uniq_txn_fingerprint_per_source"
            ),
        ]
        indexes = [
            models.Index(fields=["user", "date"]),
            models.Index(fields=["data_source", "date"], name="txn_source_date_idx"),
        ]


class TransferLink(OwnedModel):
    """Two rows that are one movement of the user's own money, between two data sources.

    The debit left one source and the credit arrived in another, so neither is real spending or
    income when both sources are in view. The rules that need decrypted amounts or a look at both
    rows live in the service that creates a link.
    """

    debit = models.OneToOneField(Transaction, on_delete=models.CASCADE, related_name="debit_link")
    credit = models.OneToOneField(Transaction, on_delete=models.CASCADE, related_name="credit_link")

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=~Q(debit=F("credit")), name="link_joins_two_transactions"
            ),
        ]

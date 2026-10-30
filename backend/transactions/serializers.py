from decimal import Decimal

from rest_framework import serializers

from categories.models import Category
from datasources.models import DataSource

from .models import Transaction
from .services import _money

MAX_NOTES_LENGTH = 500


def link_of(transaction: Transaction) -> dict | None:
    """The transfer this row is part of: the link, the other row and that row's data source."""
    link = getattr(transaction, "debit_link", None)
    if link is not None:
        partner = link.credit
    else:
        link = getattr(transaction, "credit_link", None)
        partner = link.debit if link is not None else None
    if link is None:
        return None
    return {
        "id": str(link.pk),
        "partner": str(partner.pk),
        "partner_source": str(partner.data_source_id),
    }


class TransactionSerializer(serializers.ModelSerializer):
    name = serializers.CharField(max_length=200, write_only=True)
    description = serializers.CharField(allow_blank=True, write_only=True)
    # Same reason as above: the model only has amount_enc / balance_enc.
    # Stored amount is always positive; the sign lives in txn_type.
    amount = serializers.DecimalField(
        max_digits=14, decimal_places=2, min_value=Decimal("0.01"), write_only=True
    )
    balance = serializers.DecimalField(
        max_digits=14, decimal_places=2, allow_null=True, write_only=True
    )
    # Optional and encrypted: the model only has notes_enc. Blank clears the note.
    notes = serializers.CharField(
        max_length=MAX_NOTES_LENGTH, allow_blank=True, required=False, write_only=True
    )
    category = serializers.PrimaryKeyRelatedField(queryset=Category.objects.none())

    class Meta:
        model = Transaction
        fields = (
            "id",
            "data_source",
            "date",
            "txn_type",
            "category",
            "name",
            "description",
            "amount",
            "balance",
            "notes",
        )
        # Rows change source through bulk-source, which keeps the duplicate rules.
        read_only_fields = ("id", "data_source")

    def get_fields(self):
        fields = super().get_fields()
        request = self.context.get("request")
        if request is not None:
            fields["category"].queryset = Category.objects.filter(user=request.user)
        return fields

    def validate(self, attrs):
        # A link says these two rows are the same money, so the amount and direction must hold.
        if {"amount", "txn_type"} & set(attrs) and self.instance and link_of(self.instance):
            raise serializers.ValidationError(
                "Unlink this transaction before changing its amount or type."
            )
        return attrs

    def to_representation(self, instance):
        data = super().to_representation(instance)
        cipher = self.context["cipher"]  # one DEK load per request, built in the view

        def dec(blob, ctx):
            return cipher.decrypt(bytes(blob), ctx).decode()  # bytes(): Postgres gives memoryview

        data["name"] = dec(instance.name_enc, "txn.name")
        data["description"] = dec(instance.description_enc, "txn.description")
        data["amount"] = dec(instance.amount_enc, "txn.amount")
        data["balance"] = (
            dec(instance.balance_enc, "txn.balance") if instance.balance_enc is not None else None
        )
        data["notes"] = dec(instance.notes_enc, "txn.notes") if instance.notes_enc is not None else ""
        data["link"] = link_of(instance)
        return data

    def update(self, instance, validated_data):
        cipher = self.context["cipher"]
        # Same context strings as create_transaction, or decryption would fail later.
        if "name" in validated_data:
            instance.name_enc = cipher.encrypt(validated_data.pop("name").encode(), "txn.name")
        if "description" in validated_data:
            instance.description_enc = cipher.encrypt(
                validated_data.pop("description").encode(), "txn.description"
            )
        if "amount" in validated_data:
            amount = _money(validated_data.pop("amount"))
            instance.amount_enc = cipher.encrypt(amount.encode(), "txn.amount")
        if "balance" in validated_data:
            balance = validated_data.pop("balance")
            instance.balance_enc = (
                cipher.encrypt(_money(balance).encode(), "txn.balance")
                if balance is not None
                else None
            )
        if "notes" in validated_data:
            notes = validated_data.pop("notes").strip()
            instance.notes_enc = cipher.encrypt(notes.encode(), "txn.notes") if notes else None
        if "category" in validated_data:
            instance.category = validated_data.pop("category")

        # date / txn_type are plain columns, so the generic path handles them.
        for field, value in validated_data.items():
            setattr(instance, field, value)
        # instance.fingerprint is deliberately NOT recomputed: it identifies the row as it
        # appeared in the bank statement, so re-importing the same file still dedupes.
        instance.save()
        return instance


MAX_BULK_TRANSACTIONS = 200  # one drop onto a bucket; a page shows 50


class BulkDeleteSerializer(serializers.Serializer):
    """POST /api/transactions/bulk-delete/: delete many transactions at once."""

    transactions = serializers.ListField(
        child=serializers.UUIDField(), min_length=1, max_length=MAX_BULK_TRANSACTIONS
    )


class BulkSourceSerializer(serializers.Serializer):
    """POST /api/transactions/bulk-source/: move many transactions to another data source."""

    transactions = serializers.ListField(
        child=serializers.UUIDField(), min_length=1, max_length=MAX_BULK_TRANSACTIONS
    )
    data_source = serializers.PrimaryKeyRelatedField(queryset=DataSource.objects.none())

    def get_fields(self):
        fields = super().get_fields()
        fields["data_source"].queryset = DataSource.objects.filter(user=self.context["request"].user)
        return fields


class LinkSerializer(serializers.Serializer):
    """Two transactions that are one transfer, in either order."""

    first = serializers.UUIDField()
    second = serializers.UUIDField()


class BulkLinkSerializer(serializers.Serializer):
    """POST /api/transactions/links/bulk/: approve many suggested transfers at once."""

    pairs = serializers.ListField(child=LinkSerializer(), min_length=1, max_length=200)


class BulkCategorySerializer(serializers.Serializer):
    """POST /api/transactions/bulk-category/: move many transactions into one category
    (dropping rows onto a bucket on the Transactions page)."""

    transactions = serializers.ListField(
        child=serializers.UUIDField(), min_length=1, max_length=MAX_BULK_TRANSACTIONS
    )
    category = serializers.PrimaryKeyRelatedField(queryset=Category.objects.none())

    def get_fields(self):
        fields = super().get_fields()
        # Only the caller's own categories exist as far as this request is concerned.
        fields["category"].queryset = Category.objects.filter(user=self.context["request"].user)
        return fields

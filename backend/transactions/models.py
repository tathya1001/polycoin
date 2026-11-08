import uuid
from datetime import date as date_type

from django.apps import apps
from django.conf import settings
from django.db import models
from django.db.models import F, Q

from core.models import OwnedModel
from vault.services import cipher_for

CORE_CONTEXT = "txn.core"
SLOT_CONTEXT = "txn.slot"
CORE_FIELDS = ("date", "txn_type", "category_id", "data_source_id")


def encode_core(date: date_type, txn_type: str, category_id, data_source_id) -> bytes:
    return f"{date.isoformat()}|{txn_type}|{category_id}|{data_source_id}".encode()


def decode_core(raw: bytes) -> tuple[date_type, str, uuid.UUID, uuid.UUID]:
    day, txn_type, category_id, data_source_id = raw.decode().split("|")
    return date_type.fromisoformat(day), txn_type, uuid.UUID(category_id), uuid.UUID(data_source_id)


def slot_of(cipher, data_source_id, fingerprint) -> bytes:
    """A keyed hash of (source, fingerprint): unique per user, so one source can't hold the same
    transaction twice, even with two imports running at once (Phase 12.2, D12)."""
    return cipher.blind_index(f"{data_source_id}|".encode() + bytes(fingerprint), SLOT_CONTEXT)


class Transaction(OwnedModel):
    """One row of a statement. Everything about it is encrypted with the owner's key.

    Phase 12.2 (D9, D11): its date, type, category and data source live together in `core_enc`.
    They read and write as ordinary attributes (`txn.date`, `txn.category = food`): reading
    decrypts the core once per object, and `save()` encrypts it again. The database can't filter
    or sort on them any more; transactions/index.py does that in Python.
    """

    class Type(models.TextChoices):
        CREDIT = "credit"
        DEBIT = "debit"

    core_enc = models.BinaryField()  # date|type|category id|source id
    name_enc = models.BinaryField()
    description_enc = models.BinaryField()
    amount_enc = models.BinaryField()
    balance_enc = models.BinaryField(null=True)
    # The user's own optional note. NULL means "no note" (not an encrypted empty string).
    # Not part of `fingerprint`: editing a note must never affect re-import dedupe.
    notes_enc = models.BinaryField(null=True)
    # A keyed hash of what makes two transactions "the same", whatever their source.
    fingerprint = models.BinaryField(max_length=32)
    slot = models.BinaryField(max_length=32)  # see slot_of

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "slot"], name="uniq_txn_slot_per_user"),
        ]
        indexes = [models.Index(fields=["user", "fingerprint"], name="txn_user_fingerprint_idx")]

    # --- the encrypted core ----------------------------------------------------------------------

    def _core(self) -> dict:
        core = self.__dict__.get("_core_values")
        if core is None:
            core = {}
            if self.core_enc:
                raw = cipher_for(self.user_id).decrypt(self.core_enc, CORE_CONTEXT)
                core = dict(zip(CORE_FIELDS, decode_core(raw)))
            self.__dict__["_core_values"] = core
        return core

    def _set_core(self, field: str, value) -> None:
        self._core()[field] = value
        self.__dict__["_core_dirty"] = True

    def seal(self) -> None:
        """Encrypt the core (and work out the slot) from the attributes. save() does this."""
        core = self._core()
        missing = [field for field in CORE_FIELDS if core.get(field) is None]
        if missing:
            raise ValueError(f"A transaction needs {', '.join(missing)}.")
        cipher = cipher_for(self.user_id)
        self.core_enc = cipher.encrypt(encode_core(*(core[f] for f in CORE_FIELDS)), CORE_CONTEXT)
        self.slot = slot_of(cipher, core["data_source_id"], self.fingerprint)
        self.__dict__["_core_dirty"] = False

    def save(self, *args, **kwargs):
        if self.__dict__.get("_core_dirty"):
            self.seal()
            if kwargs.get("update_fields") is not None:
                kwargs["update_fields"] = {*kwargs["update_fields"], "core_enc", "slot"}
        super().save(*args, **kwargs)

    def refresh_from_db(self, *args, **kwargs):
        for key in ("_core_values", "_core_dirty", "_category", "_data_source"):
            self.__dict__.pop(key, None)
        super().refresh_from_db(*args, **kwargs)

    date = property(lambda self: self._core().get("date"), lambda self, v: self._set_core("date", v))
    txn_type = property(
        lambda self: self._core().get("txn_type"), lambda self, v: self._set_core("txn_type", v)
    )
    category_id = property(
        lambda self: self._core().get("category_id"),
        lambda self, v: self._set_core("category_id", v),
    )
    data_source_id = property(
        lambda self: self._core().get("data_source_id"),
        lambda self, v: self._set_core("data_source_id", v),
    )

    def _related(self, cache: str, model: str, pk):
        obj = self.__dict__.get(cache)
        if obj is None or obj.pk != pk:
            obj = apps.get_model(model).objects.get(pk=pk)
            self.__dict__[cache] = obj
        return obj

    @property
    def category(self):
        return self._related("_category", "categories.Category", self.category_id)

    @category.setter
    def category(self, value):
        self._set_core("category_id", value.pk)
        self.__dict__["_category"] = value

    @property
    def data_source(self):
        return self._related("_data_source", "datasources.DataSource", self.data_source_id)

    @data_source.setter
    def data_source(self, value):
        self._set_core("data_source_id", value.pk)
        self.__dict__["_data_source"] = value

    def attach(self, categories: dict | None = None, sources: dict | None = None) -> None:
        """Hand over already-loaded categories and sources ({id: obj}), so reading
        `.category` or `.data_source` on many rows doesn't query once per row."""
        if categories is not None and self.category_id in categories:
            self.__dict__["_category"] = categories[self.category_id]
        if sources is not None and self.data_source_id in sources:
            self.__dict__["_data_source"] = sources[self.data_source_id]

    # --- the transfer link (D15) ---------------------------------------------------------------

    @property
    def link(self):
        """This row's TransferLink, whichever side it is on, or None."""
        for name in ("link_as_first", "link_as_second"):
            try:
                return getattr(self, name)
            except TransferLink.DoesNotExist:
                continue
        return None

    @property
    def partner(self):
        link = self.link
        if link is None:
            return None
        return link.second if link.first_id == self.pk else link.first


class TransferLink(OwnedModel):
    """Two rows that are one movement of the user's own money, between two data sources.

    The debit left one source and the credit arrived in another, so neither is real spending or
    income when both sources are in view. The rules that need decrypted amounts or a look at both
    rows live in the service that creates a link.

    Phase 12.2 (D15): the two sides are `first` and `second`, in id order, so the database can't
    tell which is the debit; that comes from decrypting their cores (`debit_and_credit`).
    """

    first = models.OneToOneField(
        Transaction, on_delete=models.CASCADE, related_name="link_as_first"
    )
    second = models.OneToOneField(
        Transaction, on_delete=models.CASCADE, related_name="link_as_second"
    )

    class Meta:
        constraints = [
            # Also rules out the same pair stored twice in the opposite order.
            models.CheckConstraint(condition=Q(first__lt=F("second")), name="link_in_id_order"),
        ]

    @classmethod
    def between(cls, user, one, other) -> "TransferLink":
        first, second = sorted((one, other), key=lambda txn: str(txn.pk))
        return cls(user=user, first=first, second=second)

    @classmethod
    def create_between(cls, user, one, other) -> "TransferLink":
        link = cls.between(user, one, other)
        link.save()
        return link

    def debit_and_credit(self):
        """(debit row, credit row), from the decrypted types."""
        return (self.first, self.second) if self.first.txn_type == "debit" else (self.second, self.first)


class CoreIndex(models.Model):
    """Every core of one user's transactions in one encrypted blob (transactions/index.py), so a
    read decrypts once instead of once per row. A cache, never the source of truth: it is rebuilt
    from the rows whenever `built_generation` differs from `generation`, which a database trigger
    raises on every insert, update and delete of the user's transactions (migration 0010)."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, primary_key=True, on_delete=models.CASCADE, related_name="+"
    )
    generation = models.BigIntegerField(default=0)  # raised by the trigger only
    built_generation = models.BigIntegerField(null=True)  # the generation `blob` was built at
    row_count = models.IntegerField(default=0)  # a second guard: compared with COUNT(*)
    blob = models.BinaryField(null=True)  # encrypted with the user's key (index.INDEX_CONTEXT)

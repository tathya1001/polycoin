"""A user's data sources: seeding, names and order.

The names are encrypted, so everything that shows one reads it through `sources_for`.
"""

import re
import uuid

from django.db import IntegrityError, transaction

from categories.colors import next_color
from insights.formula import source_key

from .models import MAX_SOURCE_NAME, MAX_SOURCES_PER_USER, DataSource

DEFAULT_NAME = "Main"
SOURCE_NAME = "source.name"  # the ciphertext's context
SOURCE_INDEX = "source.index"  # the blind index's context
_NOT_IN_A_NAME = re.compile(r"[.\[\]]")  # they would break a formula's reference to the source


class SourceError(ValueError):
    """The request can't be done. `code` is for the UI, the message is for the person."""

    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


def seed_default_source(user) -> DataSource:
    """The user's first source. Idempotent: re-running (or racing) never makes a second one."""
    source, _ = DataSource.objects.get_or_create(user=user, name_index=None)
    return source


def first_source(user) -> DataSource:
    """Where transactions go when nothing chooses a source. Every user has at least one."""
    return DataSource.objects.filter(user=user).first() or seed_default_source(user)


def clean_name(raw) -> str:
    """The name as it is stored. Raises SourceError if it can't be used."""
    name = " ".join(raw.split()) if isinstance(raw, str) else ""
    if not name:
        raise SourceError("invalid_name", "Give the data source a name.")
    if len(name) > MAX_SOURCE_NAME:
        raise SourceError("invalid_name", f"Use at most {MAX_SOURCE_NAME} characters.")
    if _NOT_IN_A_NAME.search(name):
        raise SourceError("invalid_name", "A name can't contain a dot or square brackets.")
    return name


def _name_columns(cipher, name: str) -> dict:
    return {
        "name_enc": cipher.encrypt(name.encode(), SOURCE_NAME),
        "name_index": cipher.blind_index(source_key(name).encode(), SOURCE_INDEX),
    }


def _free_default_name(taken: set[str]) -> str:
    name, number = DEFAULT_NAME, 1
    while source_key(name) in taken:
        number += 1
        name = f"{DEFAULT_NAME} {number}"
    return name


def sources_for(user, cipher) -> list[DataSource]:
    """The user's sources in their order, each with its plain text in `.name`.

    A first source is created with no name, because a migration has no keys to encrypt one. It
    gets its name here, the first time anything reads it.
    """
    sources = list(DataSource.objects.filter(user=user))
    if not sources:
        sources = [seed_default_source(user)]
    for source in sources:
        if source.name_enc is not None:
            source.name = cipher.decrypt(bytes(source.name_enc), SOURCE_NAME).decode()
    for source in sources:
        if source.name_enc is None:
            source.name = _free_default_name(
                {source_key(s.name) for s in sources if s.name_enc is not None}
            )
            columns = _name_columns(cipher, source.name)
            # A request running at the same moment does the same, and one of them wins.
            DataSource.objects.filter(pk=source.pk, name_index__isnull=True).update(**columns)
    return sources


def get_source(user, raw_id) -> DataSource | None:
    """The user's source with this id, or None if the id is bad or belongs to someone else."""
    try:
        return DataSource.objects.filter(user=user, pk=uuid.UUID(str(raw_id))).first()
    except ValueError:
        return None


def create_source(user, cipher, raw_name, color: str | None = None) -> DataSource:
    name = clean_name(raw_name)
    sources = sources_for(user, cipher)
    if len(sources) >= MAX_SOURCES_PER_USER:
        raise SourceError("too_many", f"You can have at most {MAX_SOURCES_PER_USER} data sources.")
    position = max((source.position for source in sources), default=-1) + 1
    try:
        with transaction.atomic():
            source = DataSource.objects.create(
                user=user,
                color=color or next_color(source.color for source in sources),
                position=position,
                **_name_columns(cipher, name),
            )
    except IntegrityError:
        raise SourceError("name_taken", "You already have a data source with that name.") from None
    source.name = name
    return source


def rename_source(source: DataSource, cipher, raw_name) -> str:
    """Stores the new name and returns it. Only the columns change: formulas that name the
    source are the caller's job, so both happen in one transaction."""
    name = clean_name(raw_name)
    columns = _name_columns(cipher, name)
    try:
        with transaction.atomic():
            DataSource.objects.filter(pk=source.pk).update(**columns)
    except IntegrityError:
        raise SourceError("name_taken", "You already have a data source with that name.") from None
    return name


def reorder_sources(user, ids: list) -> None:
    """Puts the sources in the order given. `ids` must be exactly the user's sources."""
    sources = {source.pk: source for source in DataSource.objects.filter(user=user)}
    if set(ids) != set(sources) or len(ids) != len(sources):
        raise SourceError("invalid_order", "List every data source once.")
    for position, source_id in enumerate(ids):
        sources[source_id].position = position
    DataSource.objects.bulk_update(sources.values(), ["position"])

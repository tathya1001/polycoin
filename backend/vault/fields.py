"""Encrypted text attributes on models (Phase 12.2, D11, D13).

`name = SealedText("category.name")` on a model with `name_enc` and `name_index` columns makes
`obj.name` read and write plain text, stored encrypted with the owner's key. `name_index` is a keyed
hash of the lower-case text, so the database can still enforce "no two the same" and look one up,
without being able to read it.

It subclasses `property` on purpose: Django then accepts `Model(name=...)` and `.create(name=...)`,
and DRF can write it through a declared serializer field. Reading or writing needs the owner's
key unlocked in this request (vault.services.cipher_for); otherwise it raises VaultLocked.
"""

from .services import cipher_for


def _owner_of(obj):
    return obj.user_id


class SealedText(property):
    def __init__(self, context: str, owner=_owner_of, indexed: bool = True):
        self.context = context
        self.owner = owner  # obj -> the id of the user whose key encrypts it
        self.indexed = indexed
        super().__init__(self._get, self._set)

    def __set_name__(self, model, name):
        self.enc_field = f"{name}_enc"
        self.index_field = f"{name}_index"
        self.cache = f"_{name}_plain"

    def index_for(self, owner_id, text: str) -> bytes:
        """The keyed hash of `text` as `owner_id` would store it, for lookups and uniqueness."""
        return cipher_for(owner_id).blind_index(text.casefold().encode(), f"{self.context}.index")

    def _get(self, obj):
        if self.cache in obj.__dict__:
            return obj.__dict__[self.cache]
        blob = getattr(obj, self.enc_field)
        if blob is None:
            return None
        text = cipher_for(self.owner(obj)).decrypt(blob, self.context).decode()
        obj.__dict__[self.cache] = text
        return text

    def _set(self, obj, text):
        owner = self.owner(obj)
        obj.__dict__[self.cache] = text
        setattr(obj, self.enc_field, cipher_for(owner).encrypt(text.encode(), self.context))
        if self.indexed:
            setattr(obj, self.index_field, self.index_for(owner, text))

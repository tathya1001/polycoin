import uuid

from django.db import models
from django.db.models.functions import Lower

from core.models import OwnedModel, TimeStampedModel

MAX_KEYWORDS_PER_CATEGORY = 30  # bounds the label text we embed for the category
MAX_KEYWORD_LENGTH = 60


class Category(OwnedModel):
    name = models.CharField(max_length=50)
    is_default = models.BooleanField(default=False)  # True only for "Others"

    class Meta:
        ordering = ["-is_default", "name"]  # Others first, then A-Z
        constraints = [
            models.UniqueConstraint(Lower("name"), "user", name="uniq_category_per_user"),
            models.UniqueConstraint(
                fields=["user"],
                condition=models.Q(is_default=True),
                name="one_default_category_per_user",
            ),
        ]

    def __str__(self):
        return self.name


class CategoryKeyword(TimeStampedModel):
    """A word or short phrase that helps the AI recognise a category ("cafe", "food delivery").

    Normalised on purpose:
    - There is no `user` column: the owner is category.user, so it can never disagree with it.
    - The category's own name is NOT stored here. It is always part of the AI's label for the
      category, so a rename can't leave a stale copy behind.
    - Rows are plain text with no link to any transaction. The terms are the user's own
      vocabulary, not bank data, so they are stored unencrypted.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name="keywords")
    term = models.CharField(max_length=MAX_KEYWORD_LENGTH)

    class Meta:
        ordering = [Lower("term")]
        constraints = [
            models.UniqueConstraint(Lower("term"), "category", name="uniq_keyword_per_category"),
        ]

    def __str__(self):
        return self.term

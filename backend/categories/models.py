import uuid

from django.core.validators import RegexValidator
from django.db import models

from core.models import OwnedModel, TimeStampedModel
from vault.fields import SealedText

from .colors import HEX_COLOR, OTHERS_COLOR

MAX_CATEGORY_NAME = 50
MAX_KEYWORDS_PER_CATEGORY = 30  # bounds the label text we embed for the category
MAX_KEYWORD_LENGTH = 60


class Category(OwnedModel):
    """A user's category. Its name is encrypted (Phase 12.2, D13): "Medical" or "Loan EMI" says as
    much as an amount. `name_index` (a keyed hash of the lower-case name) keeps names unique per
    user. The database can't sort by name, so lists sort with `sort_categories`."""

    name = SealedText("category.name")
    name_enc = models.BinaryField()
    name_index = models.BinaryField(max_length=32)
    is_default = models.BooleanField(default=False)  # True only for "Others"
    # "#RRGGBB" in upper case: the default colour of this category in every chart.
    color = models.CharField(
        max_length=7,
        default=OTHERS_COLOR,
        validators=[RegexValidator(HEX_COLOR.pattern, "Use a colour like #2A78D6.")],
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "name_index"], name="uniq_category_per_user"),
            models.UniqueConstraint(
                fields=["user"],
                condition=models.Q(is_default=True),
                name="one_default_category_per_user",
            ),
        ]

    def __str__(self):
        return f"category {self.pk}"  # never the name: this shows in logs and the admin


def sort_categories(categories):
    """Others first, then A-Z, as the database used to order them."""
    return sorted(categories, key=lambda category: (not category.is_default, category.name.casefold()))


def _keyword_owner(keyword):
    return keyword.category.user_id


class CategoryKeyword(TimeStampedModel):
    """A word or short phrase that helps the AI recognise a category ("cafe", "food delivery").

    Normalised on purpose:
    - There is no `user` column: the owner is category.user, so it can never disagree with it.
    - The category's own name is NOT stored here. It is always part of the AI's label for the
      category, so a rename can't leave a stale copy behind.
    - The term is encrypted with the owner's key (Phase 12.2, D13); `term_index` keeps terms unique
      per category.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name="keywords")
    term = SealedText("category.keyword", owner=_keyword_owner)
    term_enc = models.BinaryField()
    term_index = models.BinaryField(max_length=32)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["category", "term_index"], name="uniq_keyword_per_category"
            ),
        ]

    def __str__(self):
        return f"keyword {self.pk}"


def sort_keywords(keywords):
    return sorted(keywords, key=lambda keyword: keyword.term.casefold())

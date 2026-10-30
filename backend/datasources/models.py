from django.core.validators import RegexValidator
from django.db import models
from django.db.models import Q

from categories.colors import CATEGORY_COLORS, HEX_COLOR
from core.models import OwnedModel

MAX_SOURCES_PER_USER = 20
MAX_SOURCE_NAME = 40


class DataSource(OwnedModel):
    """A named group of transactions, such as one bank account's statements.

    It holds a label the user chose and a colour, never bank details. The label can still say
    which bank a user has, so it is encrypted, with a blind index that keeps it unique.

    Both name columns are NULL on a user's first source until its first use. Migrations run
    without the production keys, so the source they create cannot have an encrypted name.
    """

    name_enc = models.BinaryField(null=True)
    name_index = models.BinaryField(max_length=32, null=True)
    # "#RRGGBB" in upper case: this source's default colour in every chart.
    color = models.CharField(
        max_length=7,
        default=CATEGORY_COLORS[0],
        validators=[RegexValidator(HEX_COLOR.pattern, "Use a colour like #2A78D6.")],
    )
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["position", "created_at"]
        constraints = [
            models.UniqueConstraint(fields=["user", "name_index"], name="uniq_source_name_per_user"),
            # NULLs never clash in the constraint above, and only a first source has no name yet.
            models.UniqueConstraint(
                fields=["user"],
                condition=Q(name_index__isnull=True),
                name="one_unnamed_source_per_user",
            ),
        ]

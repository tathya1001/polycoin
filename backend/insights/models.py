import uuid

from django.db import models
from django.db.models import F, Q

from core.models import OwnedModel, TimeStampedModel

MAX_DASHBOARDS_PER_USER = 20
MAX_PANELS_PER_DASHBOARD = 30
GRID_COLUMNS = 12  # the dashboard grid's column count (frontend/lib/grid.ts); w and x must fit
MIN_PANEL_HEIGHT = 2
MAX_PANEL_HEIGHT = 30


class Dashboard(OwnedModel):
    """One tab on the /dashboard page. The name is encrypted; `position` is the tab order."""

    name_enc = models.BinaryField()
    # Encrypted JSON of the dashboard's settings (its parameter values); NULL means the defaults.
    settings_enc = models.BinaryField(null=True, blank=True)
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["position", "created_at"]


class Panel(TimeStampedModel):
    """One chart box. No `user` column: the owner is dashboard.user (like CategoryKeyword).

    Title and config are encrypted: a config can hold the user's own search text
    ("merchant_contains"). The grid position and whether the title is shown are plain
    values, since they say nothing about the user's money.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    dashboard = models.ForeignKey(Dashboard, on_delete=models.CASCADE, related_name="panels")
    title_enc = models.BinaryField()
    config_enc = models.BinaryField()
    x = models.PositiveSmallIntegerField()
    y = models.PositiveSmallIntegerField()
    w = models.PositiveSmallIntegerField()
    h = models.PositiveSmallIntegerField()
    # Off for a panel that should read as bare content, such as a note.
    show_title = models.BooleanField(default=True)

    class Meta:
        ordering = ["y", "x"]
        constraints = [
            models.CheckConstraint(
                condition=Q(w__gte=1, w__lte=GRID_COLUMNS), name="panel_width_in_grid"
            ),
            models.CheckConstraint(
                condition=Q(h__gte=MIN_PANEL_HEIGHT, h__lte=MAX_PANEL_HEIGHT),
                name="panel_height_in_range",
            ),
            # Stops a panel hanging off the right edge: x + w <= 12.
            models.CheckConstraint(
                condition=Q(x__lte=GRID_COLUMNS - F("w")), name="panel_fits_the_grid"
            ),
        ]

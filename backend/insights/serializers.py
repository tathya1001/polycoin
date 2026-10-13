from django.db.models import F, Max
from rest_framework import serializers

from . import services
from .models import (
    GRID_COLUMNS,
    MAX_DASHBOARDS_PER_USER,
    MAX_PANEL_HEIGHT,
    MAX_PANELS_PER_DASHBOARD,
    MIN_PANEL_HEIGHT,
    Dashboard,
    Panel,
)
from .spec import SpecError, validate_spec
from .templates import TEMPLATES

MAX_NAME_LENGTH = 60
MAX_TITLE_LENGTH = 80
MAX_ROW = 1000  # far below the 32767 the column could hold; no real dashboard gets this tall
DEFAULT_PANEL_WIDTH = 6
DEFAULT_PANEL_HEIGHT = 4


class PanelSerializer(serializers.ModelSerializer):
    """How a panel is shown (read-only). Needs context["cipher"]."""

    class Meta:
        model = Panel
        fields = ("id", "x", "y", "w", "h")
        read_only_fields = fields

    def to_representation(self, panel):
        data = super().to_representation(panel)
        cipher = self.context["cipher"]
        data["title"] = services.decrypt_text(cipher, panel.title_enc, services.PANEL_TITLE)
        try:
            data["config"] = services.decrypt_config(cipher, panel.config_enc)
        except SpecError as problem:
            # A config saved by an older version that no longer validates: show the panel
            # as broken instead of failing the whole dashboard with a 500.
            data["config"] = None
            data["config_error"] = problem.code
        return data


class DashboardSerializer(serializers.ModelSerializer):
    """Needs context["cipher"] and context["request"]. The name is write-only plaintext in,
    decrypted text out, the same shape as TransactionSerializer."""

    name = serializers.CharField(max_length=MAX_NAME_LENGTH, write_only=True)
    template = serializers.ChoiceField(choices=sorted(TEMPLATES), write_only=True, required=False)
    position = serializers.IntegerField(
        min_value=0, max_value=MAX_DASHBOARDS_PER_USER - 1, required=False
    )

    class Meta:
        model = Dashboard
        fields = ("id", "name", "position", "template")
        read_only_fields = ("id",)

    def validate_name(self, value):
        return " ".join(value.split())  # tidy inner whitespace; the field already trimmed the ends

    def validate(self, attrs):
        if self.instance is not None and "template" in attrs:
            raise serializers.ValidationError("A template can only be used when creating.")
        if self.instance is None:  # creating, not editing
            user = self.context["request"].user
            if Dashboard.objects.filter(user=user).count() >= MAX_DASHBOARDS_PER_USER:
                raise serializers.ValidationError(
                    f"You can have at most {MAX_DASHBOARDS_PER_USER} dashboards."
                )
        return attrs

    def to_representation(self, dashboard):
        data = super().to_representation(dashboard)
        cipher = self.context["cipher"]
        data["name"] = services.decrypt_text(cipher, dashboard.name_enc, services.DASHBOARD_NAME)
        return data

    def create(self, validated_data):
        cipher = self.context["cipher"]
        name = validated_data.pop("name")
        template = validated_data.pop("template", None)
        user = validated_data["user"]  # added by perform_create
        position = validated_data.get("position", Dashboard.objects.filter(user=user).count())
        if template:
            return services.create_from_template(user, cipher, name, template, position)
        return Dashboard.objects.create(
            user=user,
            name_enc=services.encrypt_text(cipher, name, services.DASHBOARD_NAME),
            position=position,
        )

    def update(self, instance, validated_data):
        if "name" in validated_data:
            instance.name_enc = services.encrypt_text(
                self.context["cipher"], validated_data["name"], services.DASHBOARD_NAME
            )
        if "position" in validated_data:
            instance.position = validated_data["position"]
        instance.save()
        return instance


class DashboardDetailSerializer(DashboardSerializer):
    """What a single dashboard returns: the same fields plus its panels."""

    def to_representation(self, dashboard):
        data = super().to_representation(dashboard)
        data["panels"] = PanelSerializer(
            dashboard.panels.all(), many=True, context=self.context
        ).data
        return data


def _grid(low: int, high: int, required: bool):
    return serializers.IntegerField(min_value=low, max_value=high, required=required)


def _check_fits(x: int, w: int) -> None:
    """Each field is range-checked on its own; this is the rule that spans two of them."""
    if x + w > GRID_COLUMNS:
        raise serializers.ValidationError(
            f"A panel must fit inside the {GRID_COLUMNS}-column grid (x + w is at most "
            f"{GRID_COLUMNS})."
        )


class PanelUpdateSerializer(serializers.Serializer):
    """Title and config only. Needs context["cipher"]. Moving and resizing go through the
    layout endpoint instead, so the grid can never be half-saved."""

    title = serializers.CharField(max_length=MAX_TITLE_LENGTH, allow_blank=True)
    config = serializers.DictField()

    def validate_title(self, value):
        return " ".join(value.split())

    def validate_config(self, value):
        try:
            return validate_spec(value)
        except SpecError as problem:
            raise serializers.ValidationError(problem.detail) from None

    def update(self, panel, validated_data):
        cipher = self.context["cipher"]
        if "title" in validated_data:
            panel.title_enc = services.encrypt_text(
                cipher, validated_data["title"], services.PANEL_TITLE
            )
        if "config" in validated_data:
            panel.config_enc = services.encrypt_config(cipher, validated_data["config"])
        panel.save()
        return panel


class PanelCreateSerializer(PanelUpdateSerializer):
    """Needs context["cipher"] and context["dashboard"]. The grid is optional: leave it out
    and the panel goes at the bottom."""

    x = _grid(0, GRID_COLUMNS - 1, required=False)
    y = _grid(0, MAX_ROW, required=False)
    w = _grid(1, GRID_COLUMNS, required=False)
    h = _grid(MIN_PANEL_HEIGHT, MAX_PANEL_HEIGHT, required=False)

    def validate(self, attrs):
        if self.context["dashboard"].panels.count() >= MAX_PANELS_PER_DASHBOARD:
            raise serializers.ValidationError(
                f"A dashboard can have at most {MAX_PANELS_PER_DASHBOARD} panels."
            )
        given = [key for key in "xywh" if key in attrs]
        if given and len(given) != 4:
            raise serializers.ValidationError("Give x, y, w and h together, or none of them.")
        if given:
            _check_fits(attrs["x"], attrs["w"])
        return attrs

    def create(self, validated_data):
        dashboard, cipher = self.context["dashboard"], self.context["cipher"]
        grid = {key: validated_data[key] for key in "xywh" if key in validated_data}
        if not grid:
            bottom = dashboard.panels.aggregate(bottom=Max(F("y") + F("h")))["bottom"] or 0
            grid = {"x": 0, "y": bottom, "w": DEFAULT_PANEL_WIDTH, "h": DEFAULT_PANEL_HEIGHT}
        return Panel.objects.create(
            dashboard=dashboard,
            title_enc=services.encrypt_text(cipher, validated_data["title"], services.PANEL_TITLE),
            config_enc=services.encrypt_config(cipher, validated_data["config"]),
            **grid,
        )


class LayoutItemSerializer(serializers.Serializer):
    """One entry of the bulk position save: where a panel now sits."""

    panel = serializers.UUIDField()
    x = _grid(0, GRID_COLUMNS - 1, required=True)
    y = _grid(0, MAX_ROW, required=True)
    w = _grid(1, GRID_COLUMNS, required=True)
    h = _grid(MIN_PANEL_HEIGHT, MAX_PANEL_HEIGHT, required=True)

    def validate(self, attrs):
        _check_fits(attrs["x"], attrs["w"])
        return attrs

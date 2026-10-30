from rest_framework import serializers

from categories.colors import is_hex_color


class ColorField(serializers.CharField):
    def to_internal_value(self, data):
        value = super().to_internal_value(data).upper()
        if not is_hex_color(value):
            raise serializers.ValidationError("Use a colour like #2A78D6.")
        return value


class WriteSourceSerializer(serializers.Serializer):
    """The name's own rules are in services.clean_name, which every write goes through."""

    name = serializers.CharField(required=False, allow_blank=True, trim_whitespace=False)
    color = ColorField(required=False)


class RemoveSourceSerializer(serializers.Serializer):
    """No `move_to` means the transactions are deleted with the source."""

    move_to = serializers.UUIDField(required=False, allow_null=True)


class ReorderSerializer(serializers.Serializer):
    order = serializers.ListField(child=serializers.UUIDField(), min_length=1, max_length=20)

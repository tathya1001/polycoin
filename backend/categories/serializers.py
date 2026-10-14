from rest_framework import serializers

from .colors import is_hex_color, next_color
from .models import MAX_KEYWORDS_PER_CATEGORY, Category, CategoryKeyword


class KeywordSerializer(serializers.ModelSerializer):
    """Needs context["category"]: the category the term is being added to."""

    class Meta:
        model = CategoryKeyword
        fields = ("id", "term")
        read_only_fields = ("id",)

    def validate_term(self, value):
        value = " ".join(value.split())  # tidy inner whitespace; the field already trimmed the ends
        category = self.context["category"]

        if category.is_default:
            raise serializers.ValidationError("The default category can't have keywords.")
        if value.lower() == category.name.lower():
            raise serializers.ValidationError("The category name is already used automatically.")
        if category.keywords.filter(term__iexact=value).exists():
            raise serializers.ValidationError("That keyword is already on this category.")
        if category.keywords.count() >= MAX_KEYWORDS_PER_CATEGORY:
            raise serializers.ValidationError(
                f"A category can have at most {MAX_KEYWORDS_PER_CATEGORY} keywords."
            )
        return value


class CategorySerializer(serializers.ModelSerializer):
    keywords = KeywordSerializer(many=True, read_only=True)
    # Declared by hand so lower case ("#ff7a1a") is accepted and normalised in validate_color;
    # the model's own validator would reject it before validate_color ever ran.
    color = serializers.CharField(max_length=7, required=False)

    class Meta:
        model = Category
        fields = ("id", "name", "is_default", "color", "keywords")
        read_only_fields = ("id", "is_default")  # clients can't mint a second "default"

    def validate_color(self, value):
        value = value.upper()
        if not is_hex_color(value):
            raise serializers.ValidationError("Use a colour like #2A78D6.")
        return value

    def create(self, validated_data):
        # A new category takes the first palette colour the user is not using yet.
        if "color" not in validated_data:
            mine = Category.objects.filter(user=validated_data["user"])
            validated_data["color"] = next_color(mine.values_list("color", flat=True))
        return super().create(validated_data)

    def validate_name(self, value):
        user = self.context["request"].user

        if self.instance and self.instance.is_default and value != self.instance.name:
            raise serializers.ValidationError("The default category can't be renamed.")

        clash = Category.objects.filter(user=user, name__iexact=value)
        if self.instance:
            clash = clash.exclude(pk=self.instance.pk)  # renaming to its own name is fine
        if clash.exists():
            raise serializers.ValidationError("You already have a category with that name.")
        return value

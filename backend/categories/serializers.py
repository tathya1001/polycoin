from rest_framework import serializers

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

    class Meta:
        model = Category
        fields = ("id", "name", "is_default", "keywords")
        read_only_fields = ("id", "is_default")  # clients can't mint a second "default"

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

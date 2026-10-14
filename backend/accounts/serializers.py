from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers
from django.db import transaction
from vault.services import create_user_key
from categories.services import seed_default_categories
from .models import User, UserPreferences


class RegisterSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate_email(self, value):
        value = User.objects.normalize_email(value)
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("A user with that email already exists.")
        return value

    def validate_password(self, value):
        validate_password(value)
        return value

    def create(self, validated_data):
        with transaction.atomic():  # a user must never exist without a key
            user = User.objects.create_user(**validated_data)
            create_user_key(user)
            seed_default_categories(user)
        return user



class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ("id", "email", "date_joined")
        read_only_fields = fields

class PreferencesSerializer(serializers.ModelSerializer):
    """Whitelisted by construction: only the fields listed here can ever be written, and
    `font` and `chart_quality` are ChoiceFields, so only the values listed in UserPreferences
    are accepted."""

    class Meta:
        model = UserPreferences
        fields = ("font", "chart_quality")


class DeleteDataSerializer(serializers.Serializer):
    """Erasing data needs the account password again, even though the user is signed in:
    a stolen session, or a stranger at an unlocked laptop, must not be able to wipe it."""

    password = serializers.CharField(write_only=True, trim_whitespace=False)

    def validate_password(self, value):
        if not self.context["request"].user.check_password(value):
            raise serializers.ValidationError("Incorrect password.")
        return value

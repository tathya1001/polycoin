from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from rest_framework import serializers

from categories.services import seed_default_categories
from datasources.services import seed_default_source
from vault.services import create_user_key

from .models import User, UserPreferences
from .services import birth_date_problem, set_birth_date


def _adult_birth_date(value):
    problem = birth_date_problem(value)
    if problem:
        raise serializers.ValidationError(problem)
    return value


class RegisterSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)
    birth_date = serializers.DateField(write_only=True)  # YYYY-MM-DD; 18+ only

    def validate_email(self, value):
        value = User.objects.normalize_email(value)
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("A user with that email already exists.")
        return value

    def validate_password(self, value):
        validate_password(value)
        return value

    def validate_birth_date(self, value):
        return _adult_birth_date(value)

    def create(self, validated_data):
        birth_date = validated_data.pop("birth_date")
        with transaction.atomic():  # a user must never exist without a key
            user = User.objects.create_user(**validated_data)
            # Locked with the password and a recovery key (Phase 12.1). The view shows the
            # recovery key once; it is never stored in a form that could show it again.
            self.recovery_key = create_user_key(user, validated_data["password"])
            set_birth_date(user, birth_date)  # needs the key: it is encrypted with it
            seed_default_categories(user)
            seed_default_source(user)
        return user



class BirthDateSerializer(serializers.Serializer):
    """For accounts made before dates of birth were asked for."""

    birth_date = serializers.DateField()

    def validate_birth_date(self, value):
        return _adult_birth_date(value)


class UserSerializer(serializers.ModelSerializer):
    # Whether the app must ask for the date of birth before anything else. The date itself is
    # never sent back.
    birth_date_required = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ("id", "email", "date_joined", "birth_date_required")
        read_only_fields = fields

    def get_birth_date_required(self, user) -> bool:
        return user.birth_date_enc is None

class PreferencesSerializer(serializers.ModelSerializer):
    """Whitelisted by construction: only the fields listed here can ever be written, and
    `font`, `chart_quality` and `theme` are ChoiceFields, so only the values listed in
    UserPreferences are accepted."""

    class Meta:
        model = UserPreferences
        fields = ("font", "chart_quality", "theme")


class ConfirmPasswordSerializer(serializers.Serializer):
    """Erasing data or deleting the account needs the account password again, even though the
    user is signed in: a stolen session, or a stranger at an unlocked laptop, must not be able
    to wipe it."""

    password = serializers.CharField(write_only=True, trim_whitespace=False)

    def validate_password(self, value):
        if not self.context["request"].user.check_password(value):
            raise serializers.ValidationError("Incorrect password.")
        return value


class ChangePasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True, trim_whitespace=False)
    new_password = serializers.CharField(write_only=True, trim_whitespace=False)

    def validate_current_password(self, value):
        if not self.context["request"].user.check_password(value):
            raise serializers.ValidationError("Incorrect password.")
        return value

    def validate_new_password(self, value):
        validate_password(value, user=self.context["request"].user)
        return value

    def validate(self, attrs):
        if attrs["new_password"] == attrs["current_password"]:
            raise serializers.ValidationError(
                {"new_password": "Choose a password different from the current one."}
            )
        return attrs


class RecoverSerializer(serializers.Serializer):
    # Not an EmailField: a malformed address must get the same answer as an unknown one.
    email = serializers.CharField(max_length=254)
    recovery_key = serializers.CharField(max_length=100)
    new_password = serializers.CharField(write_only=True, trim_whitespace=False)

    def check_new_password(self, user):
        """Once the recovery key has matched: the new password must pass the usual rules, some of
        which compare it with the user's details."""
        try:
            validate_password(self.validated_data["new_password"], user=user)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"new_password": list(exc.messages)}) from None

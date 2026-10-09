from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers
from django.db import transaction
from vault.services import create_user_key
from categories.services import seed_default_categories
from .models import User


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
import uuid
from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.db import models


class UserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("The Email field must be set")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user
        
    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")

        return self.create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(auto_now_add=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    def __str__(self):
        return self.email


class UserPreferences(models.Model):
    """How one user likes the app to look. Created on first use (get_or_create), not at
    registration, so adding a preference never needs a data migration for existing users.

    Add a new font: one more entry in FONT_CHOICES here, plus the other places listed at the top
    of frontend/lib/fonts.ts.
    Later: a theme field goes here too.
    """

    # The ids must match frontend/lib/fonts.ts (FONT_OPTIONS).
    FONT_CHOICES = [
        ("geist", "Geist"),
        ("inter", "Inter"),
        ("space-grotesk", "Space Grotesk"),
        ("plex-sans", "IBM Plex Sans"),
        ("geologica", "Geologica"),
        ("source-serif", "Source Serif 4"),
        ("instrument-serif", "Instrument Serif"),
        ("bitter", "Bitter"),
        ("crimson-pro", "Crimson Pro"),
        ("spectral", "Spectral"),
        ("plex-mono", "IBM Plex Mono"),
        ("xanh-mono", "Xanh Mono"),
        ("vt323", "VT323"),
    ]
    DEFAULT_FONT = "geist"
    # How charts are drawn: "quality" = sharp vector graphics (SVG), "performance" = a pixel
    # canvas, faster when a chart has thousands of points.
    CHART_QUALITY_CHOICES = [("quality", "High quality"), ("performance", "Performance")]
    DEFAULT_CHART_QUALITY = "quality"

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="preferences")
    font = models.CharField(max_length=32, choices=FONT_CHOICES, default=DEFAULT_FONT)
    chart_quality = models.CharField(
        max_length=16, choices=CHART_QUALITY_CHOICES, default=DEFAULT_CHART_QUALITY
    )
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"preferences of {self.user}"

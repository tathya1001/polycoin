from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import User


class UserAdmin(BaseUserAdmin):
    model = User
    list_display = ["email", "is_staff", "is_active", "date_joined"]
    ordering = ["email"]
    search_fields = ["email"]
    
    
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Important dates", {"fields": ("last_login", "date_joined")}),
        ("Consent", {"fields": ("privacy_policy_version", "privacy_policy_accepted_at")}),
    )
    readonly_fields = ("date_joined", "privacy_policy_version", "privacy_policy_accepted_at")

    add_fieldsets = (
        (None, {"classes": ("wide",), "fields": ("email", "password1", "password2")}),
    )


admin.site.register(User, UserAdmin)

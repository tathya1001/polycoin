from django.contrib import admin
from django.db.models import Count

from .models import Dashboard, Panel

# Same rule as the transactions admin: names, titles and configs are shown as a few bytes
# of ciphertext, never decrypted, and every column is read-only. Dashboards and panels are
# only created through the app.


@admin.register(Dashboard)
class DashboardAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "position", "panel_count", "ciphertext_preview", "updated_at")
    list_select_related = ("user",)  # avoids one query per row
    readonly_fields = [f.name for f in Dashboard._meta.fields]

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(panel_total=Count("panels"))

    @admin.display(description="panels", ordering="panel_total")
    def panel_count(self, obj):
        return obj.panel_total

    @admin.display(description="name (ciphertext, first 8 bytes)")
    def ciphertext_preview(self, obj):
        return bytes(obj.name_enc)[:8].hex()  # hex of the first bytes, never decrypted

    def has_add_permission(self, request):
        return False


@admin.register(Panel)
class PanelAdmin(admin.ModelAdmin):
    list_display = ("id", "owner", "dashboard", "x", "y", "w", "h", "ciphertext_preview")
    list_select_related = ("dashboard__user",)
    readonly_fields = [f.name for f in Panel._meta.fields]

    @admin.display(description="user", ordering="dashboard__user")
    def owner(self, obj):
        return obj.dashboard.user  # panels have no user column of their own

    @admin.display(description="title (ciphertext, first 8 bytes)")
    def ciphertext_preview(self, obj):
        return bytes(obj.title_enc)[:8].hex()

    def has_add_permission(self, request):
        return False

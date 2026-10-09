from django.contrib import admin

from .models import Transaction


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "date", "txn_type", "category", "ciphertext_preview")
    list_select_related = ("user", "category")  # avoids one query per row

    # Every column is read-only, including the encrypted ones and the fingerprint.
    readonly_fields = [f.name for f in Transaction._meta.fields]

    @admin.display(description="name (ciphertext, first 8 bytes)")
    def ciphertext_preview(self, obj):
        return bytes(obj.name_enc)[:8].hex()  # hex of the first bytes, never decrypted

    def has_add_permission(self, request):
        return False  # transactions only come from the importer

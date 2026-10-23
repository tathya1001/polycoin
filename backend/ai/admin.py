from django.contrib import admin

from .models import RagDocument

# Same rule as the transactions and insights admins: the payload (vector + text) is shown as a
# few bytes of ciphertext, never decrypted, and every column is read-only. Documents are only
# created through the index endpoints.


@admin.register(RagDocument)
class RagDocumentAdmin(admin.ModelAdmin):
    list_display = (
        "id", "user", "transaction_id", "model", "short_digest", "dims", "text_version",
        "ciphertext_preview", "source_updated_at",
    )  # fmt: skip
    list_select_related = ("user",)  # avoids one query per row
    list_filter = ("model",)  # model names say nothing about the user's money
    readonly_fields = [f.name for f in RagDocument._meta.fields]

    @admin.display(description="digest", ordering="model_digest")
    def short_digest(self, obj):
        return obj.model_digest[:19]  # "sha256:" + 12 hex characters is enough to tell them apart

    @admin.display(description="payload (ciphertext, first 8 bytes)")
    def ciphertext_preview(self, obj):
        return bytes(obj.payload_enc)[:8].hex()  # hex of the first bytes, never decrypted

    def has_add_permission(self, request):
        return False

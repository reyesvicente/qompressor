from django.contrib import admin
from django.utils.html import format_html

from .models import Blob, Chunk, Dictionary, ManifestEntry


@admin.register(Blob)
class BlobAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "status",
        "policy",
        "human_raw",
        "human_stored",
        "ratio_display",
        "dedup_display",
        "created_at",
    )
    list_filter = ("status", "policy", "corpus_key")
    search_fields = ("name", "sha256", "id")
    readonly_fields = (
        "id",
        "raw_size",
        "stored_size",
        "logical_size",
        "chunk_count",
        "dedup_hits",
        "sha256",
        "encode_seconds",
        "created_at",
        "completed_at",
    )

    @admin.display(description="raw")
    def human_raw(self, obj):
        return _bytes(obj.raw_size)

    @admin.display(description="written")
    def human_stored(self, obj):
        return _bytes(obj.stored_size)

    @admin.display(description="ratio")
    def ratio_display(self, obj):
        return format_html("<b>{:.2f}x</b>", obj.ratio)

    @admin.display(description="dedup")
    def dedup_display(self, obj):
        return f"{obj.dedup_rate * 100:.0f}%"


@admin.register(Chunk)
class ChunkAdmin(admin.ModelAdmin):
    list_display = ("digest", "codec_id", "raw_size", "stored_size", "refcount")
    list_filter = ("codec_id",)
    search_fields = ("digest",)
    # No bulk delete: chunks are reclaimed by the sweeper, which checks
    # refcounts. Deleting one by hand can silently destroy another object.
    actions = None

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Dictionary)
class DictionaryAdmin(admin.ModelAdmin):
    list_display = ("corpus_key", "id", "sample_count", "trained_at", "retired_at")
    list_filter = ("corpus_key",)
    # A dictionary is undeletable by construction: chunks encoded against it
    # cannot be decoded without it.
    actions = None

    def has_delete_permission(self, request, obj=None):
        return False


admin.site.register(ManifestEntry)


def _bytes(n: int) -> str:
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if n < 1024:
            return f"{n:.0f} {unit}"
        n /= 1024
    return f"{n:.1f} PiB"

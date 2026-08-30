from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models, transaction
from django.db.models import F

from .pipeline import HASH_BYTES


class Dictionary(models.Model):
    """A trained zstd dictionary.

    Append-only and effectively undeletable. Retraining creates a NEW row;
    the old one must stay resolvable forever or every chunk encoded against it
    becomes permanently unreadable. There is deliberately no admin delete
    action and no cascade onto this table.
    """

    id = models.BigAutoField(primary_key=True)
    corpus_key = models.CharField(
        max_length=128,
        db_index=True,
        help_text="Logical corpus this was trained on, e.g. 'orders.v1'. "
        "Dictionaries are only useful within a corpus.",
    )
    raw = models.BinaryField(editable=False)
    sample_count = models.PositiveIntegerField()
    trained_at = models.DateTimeField(auto_now_add=True)
    retired_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Set when this stops being used for NEW writes. Existing "
        "chunks still decode against it.",
    )

    class Meta:
        verbose_name_plural = "dictionaries"
        indexes = [models.Index(fields=["corpus_key", "-trained_at"])]

    def __str__(self) -> str:
        return f"{self.corpus_key}#{self.pk}"

    @classmethod
    def active_for(cls, corpus_key: str) -> "Dictionary | None":
        return (
            cls.objects.filter(corpus_key=corpus_key, retired_at__isnull=True)
            .order_by("-trained_at")
            .first()
        )


class Chunk(models.Model):
    """One entry in the content-addressed store.

    The digest is the primary key: identical content is one row, globally,
    across every object and every tenant. `refcount` is what makes GC safe —
    see `piedpiper.compression.tasks.collect_garbage`.
    """

    digest = models.CharField(max_length=HASH_BYTES * 2, primary_key=True)
    codec_id = models.PositiveSmallIntegerField()
    dictionary = models.ForeignKey(
        Dictionary, null=True, blank=True, on_delete=models.PROTECT
    )
    raw_size = models.PositiveIntegerField()
    stored_size = models.PositiveIntegerField()
    refcount = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["refcount"], name="chunk_refcount_idx"),
            models.Index(fields=["created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.digest[:12]} ({self.stored_size}B)"

    @property
    def savings(self) -> int:
        return self.raw_size - self.stored_size


class Blob(models.Model):
    """A logical object: a name, integrity metadata, and an ordered manifest."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        READY = "ready", "Ready"
        FAILED = "failed", "Failed"

    class Policy(models.TextChoices):
        FAST = "fast", "Fast"
        BALANCED = "balanced", "Balanced"
        ARCHIVAL = "archival", "Archival"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="blobs",
        null=True,
        blank=True,
    )
    name = models.CharField(max_length=512)
    content_type = models.CharField(max_length=128, blank=True)
    corpus_key = models.CharField(max_length=128, blank=True, db_index=True)
    policy = models.CharField(
        max_length=16, choices=Policy.choices, default=Policy.BALANCED
    )
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    error = models.TextField(blank=True)

    raw_size = models.BigIntegerField(default=0)
    stored_size = models.BigIntegerField(
        default=0, help_text="Bytes newly written to the CAS by this upload."
    )
    logical_size = models.BigIntegerField(
        default=0, help_text="Bytes this object's chunks occupy in the CAS."
    )
    chunk_count = models.PositiveIntegerField(default=0)
    dedup_hits = models.PositiveIntegerField(default=0)
    sha256 = models.CharField(max_length=64, blank=True, db_index=True)
    encode_seconds = models.FloatField(default=0.0)

    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["owner", "-created_at"])]

    def __str__(self) -> str:
        return f"{self.name} ({self.id})"

    @property
    def ratio(self) -> float:
        """Restore cost. This is the number to show a user."""
        return self.raw_size / self.logical_size if self.logical_size else 0.0

    @property
    def marginal_ratio(self) -> float:
        """Bytes in vs bytes newly billed. Infinite for a duplicate upload —
        this is the number that maps to the storage line item."""
        return self.raw_size / self.stored_size if self.stored_size else float("inf")

    @property
    def dedup_rate(self) -> float:
        return self.dedup_hits / self.chunk_count if self.chunk_count else 0.0

    @transaction.atomic
    def release(self) -> None:
        """Drop this object's claim on its chunks. Chunks are not deleted here:
        decrementing under the object lock and sweeping asynchronously keeps
        deletes O(1) and avoids a long lock on a hot CAS table."""
        digests = list(
            self.manifest.values_list("chunk_id", flat=True).distinct()  # type: ignore[attr-defined]
        )
        Chunk.objects.filter(digest__in=digests, refcount__gt=0).update(
            refcount=F("refcount") - 1
        )
        self.manifest.all().delete()  # type: ignore[attr-defined]


class ManifestEntry(models.Model):
    """Ordered chunk references. Concatenating decoded chunks by `index`
    reconstructs the object byte-for-byte."""

    blob = models.ForeignKey(Blob, on_delete=models.CASCADE, related_name="manifest")
    index = models.PositiveIntegerField()
    chunk = models.ForeignKey(Chunk, on_delete=models.PROTECT, related_name="+")

    class Meta:
        ordering = ["index"]
        constraints = [
            models.UniqueConstraint(
                fields=["blob", "index"], name="manifest_blob_index_uniq"
            )
        ]
        indexes = [models.Index(fields=["blob", "index"])]

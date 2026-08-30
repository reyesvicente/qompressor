from __future__ import annotations

import logging
import time

from celery import shared_task
from django.db import transaction
from django.db.models import F, Sum
from django.utils import timezone

from . import codecs
from .dispatch import ARCHIVAL, BALANCED, FAST
from .models import Blob, Chunk, Dictionary, ManifestEntry
from .pipeline import compress_stream
from .storage import get_chunk_store, get_staging

logger = logging.getLogger(__name__)

POLICIES = {"fast": FAST, "balanced": BALANCED, "archival": ARCHIVAL}


@shared_task(
    bind=True,
    autoretry_for=(OSError,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 5},
    acks_late=True,
)
def ingest_blob(self, blob_id: str) -> dict:
    """Chunk, dedup and encode a staged upload.

    `acks_late` plus idempotence is deliberate: if the worker dies mid-encode,
    the message is redelivered and the whole thing re-runs. That is safe
    because the CAS is content-addressed — a re-run rewrites identical chunks
    to identical keys — and because we rebuild the manifest from scratch after
    releasing the previous attempt's refcounts.
    """
    blob = Blob.objects.get(pk=blob_id)
    blob.status = Blob.Status.RUNNING
    blob.error = ""
    blob.save(update_fields=["status", "error"])

    started = time.perf_counter()
    try:
        blob.release()  # idempotence: discard any partial previous attempt

        dictionary = None
        if blob.corpus_key:
            active = Dictionary.active_for(blob.corpus_key)
            if active:
                dictionary = (active.pk, bytes(active.raw))

        store = get_chunk_store()
        with get_staging().open(blob.id) as fp:
            manifest = compress_stream(
                fp,
                store,
                policy=POLICIES[blob.policy],
                dictionary=dictionary,
            )

        _persist_manifest(blob, manifest, dictionary_id=dictionary[0] if dictionary else None)
        get_staging().discard(blob.id)

    except Exception as exc:  # noqa: BLE001 - surfaced to the caller via the row
        logger.exception("ingest failed for blob=%s", blob_id)
        Blob.objects.filter(pk=blob_id).update(
            status=Blob.Status.FAILED, error=str(exc)[:2000]
        )
        raise

    logger.info(
        "ingested blob=%s raw=%d stored=%d ratio=%.2fx dedup=%.0f%% in %.2fs",
        blob_id,
        blob.raw_size,
        blob.stored_size,
        blob.ratio,
        blob.dedup_rate * 100,
        time.perf_counter() - started,
    )
    return {
        "blob": str(blob.id),
        "ratio": blob.ratio,
        "dedup_rate": blob.dedup_rate,
    }


@transaction.atomic
def _persist_manifest(blob: Blob, manifest, dictionary_id: int | None) -> None:
    """Write the CAS index and the manifest in one transaction.

    Ordering matters: chunks first (so no manifest row can reference a missing
    chunk), then refcounts, then manifest. A crash between steps leaves
    orphaned chunks with refcount 0, which the sweeper reclaims — the opposite
    ordering would leave dangling manifest rows, which is data loss.
    """
    records = manifest.chunks
    by_digest = {}
    for record in records:
        by_digest.setdefault(record.hash, record)

    existing = set(
        Chunk.objects.filter(digest__in=by_digest).values_list("digest", flat=True)
    )

    Chunk.objects.bulk_create(
        [
            Chunk(
                digest=digest,
                codec_id=max(record.codec_id, 0),
                dictionary_id=record.dictionary_id or None,
                raw_size=record.raw_size,
                stored_size=record.stored_size,
                refcount=0,
            )
            for digest, record in by_digest.items()
            if digest not in existing
        ],
        ignore_conflicts=True,  # concurrent uploads of the same content race here
        batch_size=1000,
    )

    Chunk.objects.filter(digest__in=by_digest).update(refcount=F("refcount") + 1)

    ManifestEntry.objects.bulk_create(
        [
            ManifestEntry(blob=blob, index=record.index, chunk_id=record.hash)
            for record in records
        ],
        batch_size=2000,
    )

    blob.raw_size = manifest.raw_size
    blob.stored_size = manifest.stored_size
    blob.logical_size = manifest.logical_size
    blob.chunk_count = len(records)
    blob.dedup_hits = manifest.dedup_hits
    blob.sha256 = manifest.sha256
    blob.encode_seconds = manifest.elapsed_encode
    blob.status = Blob.Status.READY
    blob.completed_at = timezone.now()
    blob.save()


@shared_task
def collect_garbage(limit: int = 5000, min_age_seconds: int = 3600) -> dict:
    """Reclaim chunks nothing references any more.

    The age floor is not cosmetic. A chunk written by an in-flight ingest sits
    at refcount 0 until `_persist_manifest` commits; sweeping it immediately
    would delete data out from under a running job. One hour is far longer
    than any single ingest and cheap to wait.
    """
    cutoff = timezone.now() - timezone.timedelta(seconds=min_age_seconds)
    doomed = list(
        Chunk.objects.filter(refcount=0, created_at__lt=cutoff).values_list(
            "digest", flat=True
        )[:limit]
    )
    if not doomed:
        return {"deleted": 0}

    store = get_chunk_store()
    freed = 0
    for digest in doomed:
        # Delete the row first. If the object delete then fails we have an
        # orphaned blob in the CAS, which costs money; the reverse order would
        # leave an index row pointing at nothing, which costs a restore.
        with transaction.atomic():
            deleted, _ = Chunk.objects.filter(digest=digest, refcount=0).delete()
            if not deleted:
                continue
            freed += 1
            store.delete(digest)

    logger.info("gc reclaimed %d chunks", freed)
    return {"deleted": freed}


@shared_task
def train_dictionary(corpus_key: str, sample_limit: int = 4000, dict_size: int = 112 * 1024) -> dict:
    """Train a zstd dictionary from recent chunks in a corpus.

    Worth scheduling weekly per corpus. On 160-byte JSON documents a trained
    dictionary measured 3.13x against 1.12x for dictionaryless zstd — the
    single largest ratio win available anywhere in this system, and it only
    exists in the small-payload regime where the codec has no prior context.
    """
    from .storage import get_chunk_store
    from .pipeline import decode_blob

    store = get_chunk_store()
    digests = list(
        Chunk.objects.filter(
            manifestentry__blob__corpus_key=corpus_key  # type: ignore[misc]
        )
        .order_by("-created_at")
        .values_list("digest", flat=True)[:sample_limit]
    )
    samples = []
    for digest in digests:
        try:
            samples.append(decode_blob(store.get(digest), _DictProvider()))
        except Exception:  # noqa: BLE001 - a bad chunk must not fail training
            continue

    if len(samples) < 8:
        return {"trained": False, "reason": "not enough samples"}

    raw = codecs.train_dictionary(samples, dict_size=dict_size)
    dictionary = Dictionary.objects.create(
        corpus_key=corpus_key, raw=raw, sample_count=len(samples)
    )
    Dictionary.objects.filter(corpus_key=corpus_key, retired_at__isnull=True).exclude(
        pk=dictionary.pk
    ).update(retired_at=timezone.now())
    return {"trained": True, "dictionary_id": dictionary.pk, "samples": len(samples)}


class _DictProvider:
    """Resolves dictionary ids for decode. Cached per process: dictionaries are
    immutable, so there is nothing to invalidate."""

    _cache: dict[int, bytes] = {}

    def raw(self, dictionary_id: int) -> bytes:
        if dictionary_id not in self._cache:
            self._cache[dictionary_id] = bytes(
                Dictionary.objects.only("raw").get(pk=dictionary_id).raw
            )
        return self._cache[dictionary_id]


@shared_task
def report_savings() -> dict:
    """Fleet-wide numbers for the dashboard. Cheap enough to run on a beat."""
    agg = Chunk.objects.aggregate(
        stored=Sum("stored_size"), raw=Sum("raw_size"), n=Sum("refcount")
    )
    logical_raw = Blob.objects.filter(status=Blob.Status.READY).aggregate(
        raw=Sum("raw_size")
    )["raw"] or 0
    physical = agg["stored"] or 0
    return {
        "logical_bytes": logical_raw,
        "physical_bytes": physical,
        "effective_ratio": (logical_raw / physical) if physical else 0.0,
        "unique_chunks": Chunk.objects.count(),
    }

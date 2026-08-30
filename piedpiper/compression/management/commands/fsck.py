"""Verify the CAS against the index.

Run this on a schedule. A dedup store fails silently: a missing chunk does not
surface until someone restores an object that happens to reference it, which
may be years later.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from piedpiper.compression.models import Blob, Chunk
from piedpiper.compression.pipeline import content_hash, decode_blob
from piedpiper.compression.storage import get_chunk_store
from piedpiper.compression.tasks import _DictProvider


class Command(BaseCommand):
    help = "Check every chunk is present, decodable and correctly addressed."

    def add_arguments(self, parser):
        parser.add_argument("--deep", action="store_true",
                            help="Decode every chunk and re-verify its digest. Slow.")
        parser.add_argument("--limit", type=int, default=0)

    def handle(self, *args, **opts):
        store = get_chunk_store()
        dictionaries = _DictProvider()
        qs = Chunk.objects.all().order_by("created_at")
        if opts["limit"]:
            qs = qs[: opts["limit"]]

        missing = corrupt = 0
        total = 0
        for chunk in qs.iterator(chunk_size=2000):
            total += 1
            try:
                blob = store.get(chunk.digest)
            except (KeyError, OSError, FileNotFoundError):
                missing += 1
                self.stderr.write(f"MISSING  {chunk.digest}")
                continue
            if opts["deep"]:
                try:
                    decoded = decode_blob(blob, dictionaries)
                except Exception as exc:  # noqa: BLE001
                    corrupt += 1
                    self.stderr.write(f"UNDECODABLE {chunk.digest}: {exc}")
                    continue
                if content_hash(decoded) != chunk.digest:
                    corrupt += 1
                    self.stderr.write(f"DIGEST MISMATCH {chunk.digest}")

        orphaned = Chunk.objects.filter(refcount=0).count()
        dangling = Blob.objects.filter(status=Blob.Status.READY, chunk_count=0).count()

        self.stdout.write(
            self.style.SUCCESS(
                f"checked={total} missing={missing} corrupt={corrupt} "
                f"orphaned={orphaned} empty_ready_blobs={dangling}"
            )
        )
        if missing or corrupt:
            raise SystemExit(1)

"""
Storage wiring.

Two distinct concerns, deliberately not the same object:

  * staging  — the raw upload, written once, read once by the worker, deleted.
    Lives on a fast local volume. Never on S3: you would pay to PUT bytes you
    are about to delete.
  * CAS      — the deduplicated chunk store. Immutable, content-addressed,
    read-heavy, and the thing you actually pay to keep.
"""

from __future__ import annotations

import contextlib
import functools
import pathlib
import shutil
import tempfile
from typing import BinaryIO, Iterable, Iterator

from django.conf import settings

from .pipeline import FileSystemStore

__all__ = ["get_chunk_store", "get_staging", "S3ChunkStore", "Staging"]


class Staging:
    """Local scratch for in-flight uploads."""

    def __init__(self, root: str) -> None:
        self.root = pathlib.Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, blob_id) -> pathlib.Path:
        return self.root / f"{blob_id}.upload"

    def receive(self, blob_id, source: Iterable[bytes]) -> int:
        """Stream an upload to disk without buffering it in memory.

        Written to a temp file and renamed, so a half-received upload can never
        be picked up by a worker as if it were complete.
        """
        target = self._path(blob_id)
        size = 0
        fd, tmp = tempfile.mkstemp(dir=self.root)
        try:
            with open(fd, "wb") as fh:
                for part in source:
                    fh.write(part)
                    size += len(part)
            shutil.move(tmp, target)
        except BaseException:
            pathlib.Path(tmp).unlink(missing_ok=True)
            raise
        return size

    @contextlib.contextmanager
    def open(self, blob_id) -> Iterator[BinaryIO]:
        with open(self._path(blob_id), "rb") as fh:
            yield fh

    def discard(self, blob_id) -> None:
        self._path(blob_id).unlink(missing_ok=True)


class DeletableFileSystemStore(FileSystemStore):
    def delete(self, digest: str) -> None:
        self._path(digest).unlink(missing_ok=True)


class S3ChunkStore:
    """CAS on S3-compatible object storage (Spaces, R2, MinIO).

    Two things this does that a naive implementation does not:

    * `has_many` issues one LIST per prefix instead of N HEADs. On a 10k-chunk
      upload that is the difference between one round trip per chunk and a
      handful — dedup lookups, not encoding, are what make an S3-backed CAS
      slow.
    * Never overwrites. Chunk keys are content digests, so a PUT of existing
      content is pure waste; we skip it.
    """

    def __init__(self, bucket: str, client=None, prefix: str = "chunks/") -> None:
        import boto3

        self.bucket = bucket
        self.prefix = prefix
        self.client = client or boto3.client("s3")

    def _key(self, digest: str) -> str:
        return f"{self.prefix}{digest[:2]}/{digest[2:4]}/{digest}"

    def has(self, digest: str) -> bool:
        from botocore.exceptions import ClientError

        try:
            self.client.head_object(Bucket=self.bucket, Key=self._key(digest))
            return True
        except ClientError:
            return False

    def has_many(self, digests: Iterable[str]) -> set[str]:
        wanted = set(digests)
        found: set[str] = set()
        prefixes = {d[:2] for d in wanted}
        paginator = self.client.get_paginator("list_objects_v2")
        for two in prefixes:
            for page in paginator.paginate(
                Bucket=self.bucket, Prefix=f"{self.prefix}{two}/"
            ):
                for obj in page.get("Contents", []):
                    digest = obj["Key"].rsplit("/", 1)[-1]
                    if digest in wanted:
                        found.add(digest)
        return found

    def put(self, digest: str, blob: bytes) -> None:
        if self.has(digest):
            return
        self.client.put_object(Bucket=self.bucket, Key=self._key(digest), Body=blob)

    def get(self, digest: str) -> bytes:
        return self.client.get_object(Bucket=self.bucket, Key=self._key(digest))[
            "Body"
        ].read()

    def delete(self, digest: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=self._key(digest))


@functools.lru_cache(maxsize=1)
def get_chunk_store():
    backend = getattr(settings, "PIEDPIPER_CAS_BACKEND", "filesystem")
    if backend == "s3":
        return S3ChunkStore(
            bucket=settings.PIEDPIPER_CAS_BUCKET,
            prefix=getattr(settings, "PIEDPIPER_CAS_PREFIX", "chunks/"),
        )
    return DeletableFileSystemStore(settings.PIEDPIPER_CAS_ROOT)


@functools.lru_cache(maxsize=1)
def get_staging() -> Staging:
    return Staging(settings.PIEDPIPER_STAGING_ROOT)

"""
The compression pipeline.

    stream -> FastCDC -> blake2b -> dedup gate -> dispatch -> encode -> CAS

Three independent levers, applied in this order because each one makes the
next one cheaper:

  1. Dedup     removes bytes we have already stored. Free ratio, no CPU.
  2. Dispatch  avoids spending CPU on payloads with no headroom.
  3. Encode    does the actual entropy coding on what's left.

Everything here is pure Python plus the codec bindings. No Django import, so
it is directly testable and reusable from a CLI or a worker.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import BinaryIO, Iterable, Iterator, Protocol

from . import codecs
from .chunking import DEFAULT_CONFIG, ChunkerConfig, chunk_stream
from .dispatch import BALANCED, SelectionPolicy, probe, select

DICT_CODEC_ID = codecs.ZSTD_DICT_ID

__all__ = [
    "ChunkRecord",
    "Manifest",
    "ChunkStore",
    "MemoryStore",
    "FileSystemStore",
    "compress_stream",
    "decompress",
]

HASH_BYTES = 32


def content_hash(data: bytes) -> str:
    return hashlib.blake2b(data, digest_size=HASH_BYTES).hexdigest()


@dataclass(frozen=True)
class ChunkRecord:
    """One entry in a manifest. Ordered concatenation of decoded chunks
    reconstructs the object byte-for-byte."""

    index: int
    hash: str
    codec_id: int
    level: int
    raw_size: int
    stored_size: int
    deduped: bool = False
    dictionary_id: int = 0

    @property
    def ratio(self) -> float:
        return self.raw_size / self.stored_size if self.stored_size else float("inf")


@dataclass
class Manifest:
    chunks: list[ChunkRecord] = field(default_factory=list)
    raw_size: int = 0
    stored_size: int = 0  # bytes actually written this run
    logical_size: int = 0  # bytes this object's chunks occupy in the CAS
    dedup_hits: int = 0
    elapsed_encode: float = 0.0
    sha256: str = ""

    @property
    def ratio(self) -> float:
        """Ratio for this object against the CAS, i.e. what a restore costs."""
        return self.raw_size / self.logical_size if self.logical_size else float("inf")

    @property
    def marginal_ratio(self) -> float:
        """Ratio against bytes newly written. This is the number that maps to
        the storage bill; it goes to infinity for a duplicate upload."""
        return self.raw_size / self.stored_size if self.stored_size else float("inf")

    @property
    def dedup_rate(self) -> float:
        return self.dedup_hits / len(self.chunks) if self.chunks else 0.0

    @property
    def throughput_mbs(self) -> float:
        if self.elapsed_encode <= 0:
            return float("inf")
        return (self.raw_size / 1_048_576) / self.elapsed_encode

    def codec_histogram(self) -> dict[str, int]:
        hist: dict[str, int] = {}
        for c in self.chunks:
            if c.deduped:
                name = "deduped"
            elif c.codec_id == DICT_CODEC_ID:
                name = "zstd+dict"
            else:
                name = codecs.by_id(c.codec_id).name
            hist[name] = hist.get(name, 0) + 1
        return hist


# ---------------------------------------------------------------------------
# Content-addressed store
# ---------------------------------------------------------------------------


class DictionaryProvider(Protocol):
    """Resolves a dictionary id to its raw bytes.

    Dictionaries are immutable and append-only. Retraining produces a NEW id;
    the old one must stay resolvable forever or every chunk encoded against it
    becomes unreadable. This is the single most dangerous piece of state in the
    system - treat a dictionary row as undeletable.
    """

    def raw(self, dictionary_id: int) -> bytes: ...


class ChunkStore(Protocol):
    def has(self, digest: str) -> bool: ...
    def put(self, digest: str, blob: bytes) -> None: ...
    def get(self, digest: str) -> bytes: ...
    def has_many(self, digests: Iterable[str]) -> set[str]: ...


class MemoryStore:
    """Reference implementation. Also the test double."""

    def __init__(self) -> None:
        self._data: dict[str, bytes] = {}

    def has(self, digest: str) -> bool:
        return digest in self._data

    def has_many(self, digests: Iterable[str]) -> set[str]:
        return {d for d in digests if d in self._data}

    def put(self, digest: str, blob: bytes) -> None:
        self._data.setdefault(digest, blob)

    def get(self, digest: str) -> bytes:
        return self._data[digest]

    @property
    def physical_size(self) -> int:
        return sum(len(v) for v in self._data.values())

    def __len__(self) -> int:
        return len(self._data)


class FileSystemStore:
    """Fan-out CAS on local disk or a mounted volume.

    Two-level prefix so no directory exceeds a few thousand entries; ext4 and
    overlayfs both degrade badly past ~100k files in one directory.
    Writes are atomic via same-filesystem rename, so a killed worker can never
    leave a torn chunk that later reads as valid.
    """

    def __init__(self, root: str) -> None:
        import pathlib

        self.root = pathlib.Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, digest: str):
        return self.root / digest[:2] / digest[2:4] / digest

    def has(self, digest: str) -> bool:
        return self._path(digest).exists()

    def has_many(self, digests: Iterable[str]) -> set[str]:
        return {d for d in digests if self.has(d)}

    def put(self, digest: str, blob: bytes) -> None:
        import os
        import tempfile

        path = self._path(digest)
        if path.exists():
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(blob)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except FileNotFoundError:
                pass
            raise

    def get(self, digest: str) -> bytes:
        return self._path(digest).read_bytes()


# ---------------------------------------------------------------------------
# Encode / decode
# ---------------------------------------------------------------------------


def compress_stream(
    fp: BinaryIO,
    store: ChunkStore,
    policy: SelectionPolicy = BALANCED,
    cfg: ChunkerConfig = DEFAULT_CONFIG,
    dictionary: tuple[int, bytes] | None = None,
) -> Manifest:
    """Encode a stream into `store` and return its manifest.

    `dictionary` is an optional (id, raw_bytes) pair. Supplying one is the
    single biggest win available for corpora of many small, structurally
    similar payloads (JSON events, log lines, HTML fragments): below a few KB
    every general-purpose codec is effectively blind because it has no prior
    context, and a trained dictionary supplies exactly that.
    """
    manifest = Manifest()
    digest = hashlib.sha256()
    started = time.perf_counter()

    for index, chunk in enumerate(chunk_stream(fp, cfg)):
        digest.update(chunk.data)
        manifest.raw_size += chunk.size

        h = content_hash(chunk.data)

        if store.has(h):
            # Dedup hit. We deliberately do not re-encode to learn the stored
            # size: the CAS row in Postgres already knows it, and an extra
            # encode here would make duplicate uploads *more* expensive than
            # new ones.
            manifest.dedup_hits += 1
            manifest.chunks.append(
                ChunkRecord(
                    index=index,
                    hash=h,
                    codec_id=-1,  # resolved from the CAS on read
                    level=0,
                    raw_size=chunk.size,
                    stored_size=0,
                    deduped=True,
                )
            )
            continue

        pr = probe(chunk.data)
        codec, level = select(chunk.data, policy, pr)
        encoded = codec.encode(chunk.data, level)
        dict_id = 0
        header = bytes([codec.id])

        # Try the dictionary only where it can plausibly win: compressible
        # payloads. On a store-verdict chunk it is wasted CPU.
        if dictionary and codec.name != "store":
            d_id, d_raw = dictionary
            d_encoded = codecs.encode_with_dict(chunk.data, d_raw, level)
            if len(d_encoded) < len(encoded):
                encoded = d_encoded
                dict_id = d_id
                header = bytes([DICT_CODEC_ID]) + d_id.to_bytes(4, "big")

        # Guard rail: dispatch is a heuristic and heuristics are wrong
        # sometimes. If the encode did not pay for itself, fall back to store.
        # Costs one comparison and removes the entire class of
        # "compression made it bigger" incidents.
        if len(encoded) >= chunk.size:
            codec, level, encoded = codecs.by_name("store"), 0, chunk.data
            dict_id, header = 0, bytes([codec.id])

        blob = header + encoded
        store.put(h, blob)

        manifest.stored_size += len(blob)
        manifest.chunks.append(
            ChunkRecord(
                index=index,
                hash=h,
                codec_id=DICT_CODEC_ID if dict_id else codec.id,
                level=level,
                raw_size=chunk.size,
                stored_size=len(blob),
                dictionary_id=dict_id,
            )
        )

    manifest.elapsed_encode = time.perf_counter() - started
    manifest.sha256 = digest.hexdigest()
    manifest.logical_size = sum(
        len(store.get(c.hash)) for c in _unique_by_hash(manifest.chunks)
    )
    return manifest


def _unique_by_hash(chunks: list[ChunkRecord]) -> list[ChunkRecord]:
    seen: set[str] = set()
    out = []
    for c in chunks:
        if c.hash not in seen:
            seen.add(c.hash)
            out.append(c)
    return out


def decode_blob(blob: bytes, dictionaries: DictionaryProvider | None = None) -> bytes:
    """Decode one stored chunk. The header is self-describing, so a chunk can
    always be decoded from the CAS alone without consulting the manifest —
    which is what makes offline `fsck` and cross-region repair possible."""
    codec_id = blob[0]
    if codec_id == DICT_CODEC_ID:
        if dictionaries is None:
            raise ValueError("chunk needs a dictionary but no provider was given")
        dict_id = int.from_bytes(blob[1:5], "big")
        return codecs.decode_with_dict(blob[5:], dictionaries.raw(dict_id))
    return codecs.decode(blob[1:], codec_id)


def decompress(
    manifest: Manifest,
    store: ChunkStore,
    dictionaries: DictionaryProvider | None = None,
) -> Iterator[bytes]:
    """Yield the original bytes in order. A generator, so a restore streams
    straight into an HTTP response without buffering the whole object."""
    for record in manifest.chunks:
        yield decode_blob(store.get(record.hash), dictionaries)


def verify(
    manifest: Manifest,
    store: ChunkStore,
    dictionaries: DictionaryProvider | None = None,
) -> bool:
    """End-to-end integrity check against the sha256 captured at write time."""
    digest = hashlib.sha256()
    for part in decompress(manifest, store, dictionaries):
        digest.update(part)
    return digest.hexdigest() == manifest.sha256

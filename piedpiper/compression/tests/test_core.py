"""
Core tests. No Django, no database — the compression layer is deliberately
importable on its own.

The tests that matter here are the invariants, not the ratios. Ratios are a
performance regression; the invariants are data loss.
"""

from __future__ import annotations

import io
import random

import pytest

from piedpiper.compression import codecs
from piedpiper.compression.chunking import (
    DEFAULT_CONFIG,
    ChunkerConfig,
    chunk_bytes,
    chunk_stream,
)
from piedpiper.compression.dispatch import ARCHIVAL, BALANCED, FAST, probe, select
from piedpiper.compression.pipeline import (
    MemoryStore,
    compress_stream,
    content_hash,
    decompress,
    verify,
)

BACKENDS = ["native", "numpy", "python"]


def structured(n: int, seed: int = 0) -> bytes:
    rng = random.Random(seed)
    return b"".join(
        (
            '{"id":%d,"user":"u_%d","evt":"view","url":"/p/%d","s":"%016x"}\n'
            % (i, i % 997, i % 431, rng.getrandbits(64))
        ).encode()
        for i in range(n)
    )


# ---------------------------------------------------------------------------
# Chunker invariants
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"x",
        bytes(300_000),  # all zeros: pathological for a rolling hash
        random.Random(1).randbytes(400_000),
        structured(4_000),
    ],
    ids=["empty", "one-byte", "zeros", "random", "structured"],
)
def test_backends_agree(data):
    """The three chunker backends implement one definition. If they diverge,
    a deploy that changes which one loads silently orphans the dedup index."""
    results = [[c.data for c in chunk_bytes(data, backend=b)] for b in BACKENDS]
    assert results[0] == results[1] == results[2]
    assert b"".join(results[0]) == data


@pytest.mark.parametrize("read_size", [70_000, 1 << 20, 1 << 23])
def test_stream_matches_buffer(read_size):
    """A read-buffer boundary must never influence a cut. If it did, the same
    object would dedup against itself differently depending on network
    timing — the worst kind of bug to debug."""
    data = structured(30_000)
    assert [c.data for c in chunk_stream(io.BytesIO(data), read_size=read_size)] == [
        c.data for c in chunk_bytes(data)
    ]


def test_chunk_sizes_respect_bounds():
    data = structured(60_000)
    chunks = list(chunk_bytes(data))
    for chunk in chunks[:-1]:  # the tail is exempt
        assert DEFAULT_CONFIG.min_size < chunk.size <= DEFAULT_CONFIG.max_size


def test_insertion_resistance():
    """The entire justification for CDC. Fixed blocking scores ~0% here."""
    data = structured(40_000)
    before = {content_hash(c.data) for c in chunk_bytes(data)}
    after = {content_hash(c.data) for c in chunk_bytes(b"X" + data)}
    assert len(before & after) / len(before) > 0.95


def test_gear_table_is_frozen():
    """Regenerating GEAR invalidates every chunk boundary ever computed, which
    orphans the entire dedup index. This test exists so that happens as a red
    build and not as a storage bill.

    If you are here because this failed: you did not have a reason good enough.
    Changing the table requires a full re-ingest, not a new fingerprint.
    """
    import hashlib
    import struct

    from piedpiper.compression.chunking import GEAR

    assert len(GEAR) == 256
    assert len(set(GEAR)) == 256
    fingerprint = hashlib.sha256(
        b"".join(struct.pack("<Q", g) for g in GEAR)
    ).hexdigest()
    assert fingerprint == (
        "055957dd6703228324912857f67e9e7abe0268318f7613b480e5dc196bc4d6dc"
    )


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


def test_high_entropy_is_stored_not_compressed():
    data = random.Random(9).randbytes(200_000)
    codec, _ = select(data)
    assert codec.name == "store"


@pytest.mark.parametrize(
    "magic",
    [b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n", b"PK\x03\x04", b"\x1f\x8b"],
)
def test_known_containers_are_stored(magic):
    data = magic + bytes(10_000)
    codec, _ = select(data)
    assert codec.name == "store"


def test_text_is_detected():
    assert probe(structured(500)).looks_textual


@pytest.mark.parametrize("policy", [FAST, BALANCED, ARCHIVAL])
def test_policies_never_expand(policy):
    """The guard rail. Whatever the heuristic decides, output must not exceed
    input — 'compression made it bigger' is a class of incident, not a bug."""
    for data in (structured(2_000), random.Random(2).randbytes(120_000)):
        store = MemoryStore()
        manifest = compress_stream(io.BytesIO(data), store, policy)
        assert store.physical_size <= len(data) + len(manifest.chunks) * 8


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("policy", [FAST, BALANCED, ARCHIVAL])
def test_roundtrip(policy):
    data = structured(20_000)
    store = MemoryStore()
    manifest = compress_stream(io.BytesIO(data), store, policy)
    assert verify(manifest, store)
    assert b"".join(decompress(manifest, store)) == data


def test_identical_upload_writes_nothing():
    data = structured(20_000)
    store = MemoryStore()
    compress_stream(io.BytesIO(data), store)
    second = compress_stream(io.BytesIO(data), store)
    assert second.stored_size == 0
    assert second.dedup_rate == 1.0


def test_edit_writes_only_the_delta():
    data = structured(40_000)
    store = MemoryStore()
    compress_stream(io.BytesIO(data), store)

    cut = len(data) // 2
    edited = data[:cut] + structured(50, seed=99) + data[cut:]
    second = compress_stream(io.BytesIO(edited), store)

    assert second.dedup_rate > 0.90
    assert second.stored_size < len(data) // 20
    assert verify(second, store)


def test_empty_object():
    store = MemoryStore()
    manifest = compress_stream(io.BytesIO(b""), store)
    assert manifest.raw_size == 0
    assert verify(manifest, store)


# ---------------------------------------------------------------------------
# Dictionaries
# ---------------------------------------------------------------------------


def test_dictionary_roundtrip_and_win():
    docs = [
        ('{"order_id":%d,"status":"paid","currency":"PHP","total":%d}' % (i, i * 13)).encode()
        for i in range(2_000)
    ]
    raw = codecs.train_dictionary(docs[:1_000], dict_size=16 * 1024)

    plain = sum(len(codecs.encode(d, codecs.by_name("zstd"), 10)) for d in docs[1_000:])
    withd = sum(len(codecs.encode_with_dict(d, raw, 10)) for d in docs[1_000:])

    assert withd < plain / 1.5, "dictionary should be a large win below ~1 KB"
    assert codecs.decode_with_dict(codecs.encode_with_dict(docs[0], raw), raw) == docs[0]


def test_pipeline_with_dictionary_roundtrips():
    class Provider:
        def raw(self, dictionary_id):
            return raw_dict

    docs = [('{"k":%d,"v":"value_%d"}' % (i, i)).encode() for i in range(500)]
    raw_dict = codecs.train_dictionary(docs, dict_size=8 * 1024)

    data = b"".join(docs)
    store = MemoryStore()
    cfg = ChunkerConfig(min_size=64, avg_size=1024, max_size=8192)
    manifest = compress_stream(
        io.BytesIO(data), store, BALANCED, cfg, dictionary=(7, raw_dict)
    )
    assert verify(manifest, store, Provider())


# ---------------------------------------------------------------------------
# Codec registry
# ---------------------------------------------------------------------------


def test_codec_ids_are_stable():
    """Ids are written into stored chunk headers. Renumbering one makes every
    chunk carrying it decode as garbage."""
    expected = {
        0x00: "store",
        0x01: "deflate",
        0x02: "zstd",
        0x03: "zstd-max",
        0x04: "brotli",
        0x05: "brotli-text",
        0x06: "lzma",
        0x07: "bzip2",
        0x08: "gzip",
    }
    assert {cid: c.name for cid, c in codecs.CODECS.items()} == expected


@pytest.mark.parametrize("codec_id", sorted(codecs.CODECS))
def test_every_codec_roundtrips(codec_id):
    codec = codecs.by_id(codec_id)
    payload = structured(200)
    assert codec.decode(codecs.encode(payload, codec)) == payload

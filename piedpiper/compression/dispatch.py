"""
Codec dispatch.

The only defensible "compression breakthrough" is *not* compressing the wrong
thing with the wrong tool. Three cheap signals, evaluated on a sample, decide
the codec before we spend real CPU:

  1. Magic bytes      — is this already an entropy-coded container?
  2. Shannon entropy  — how much headroom is theoretically left?
  3. Printable ratio  — text-shaped payloads want a text-tuned codec.

The probe runs on <= 64 KiB regardless of object size, so dispatch cost is
O(1) per chunk and irrelevant next to the encode itself.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass

from . import codecs

try:
    import numpy as _np
except Exception:  # pragma: no cover
    _np = None

__all__ = ["Probe", "probe", "select", "SelectionPolicy"]

PROBE_BYTES = 64 * 1024

# Containers whose payload is already entropy-coded. Re-compressing these is
# a guaranteed loss: you burn CPU and typically add framing bytes.
_INCOMPRESSIBLE_MAGIC: tuple[tuple[bytes, str], ...] = (
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"GIF8", "image/gif"),
    (b"RIFF", "riff"),  # webp / wav container, checked further below
    (b"PK\x03\x04", "application/zip"),
    (b"\x1f\x8b", "application/gzip"),
    (b"BZh", "application/x-bzip2"),
    (b"\xfd7zXZ\x00", "application/x-xz"),
    (b"\x28\xb5\x2f\xfd", "application/zstd"),
    (b"7z\xbc\xaf\x27\x1c", "application/x-7z"),
    (b"\x00\x00\x00\x18ftyp", "video/mp4"),
    (b"\x00\x00\x00\x20ftyp", "video/mp4"),
    (b"\x1aE\xdf\xa3", "video/x-matroska"),
    (b"ID3", "audio/mpeg"),
    (b"OggS", "audio/ogg"),
    (b"fLaC", "audio/flac"),
    (b"%PDF", "application/pdf"),  # usually FlateDecode inside
)

_TEXTUAL_HINTS = (
    b"{",
    b"[",
    b"<",
    b"#!",
    b"<?xml",
    b"<!DOCTYPE",
    b"---",
)


@dataclass(frozen=True)
class Probe:
    size: int
    entropy: float  # bits/byte, 0..8
    printable_ratio: float
    magic: str | None
    looks_textual: bool

    @property
    def theoretical_floor(self) -> float:
        """Best achievable ratio from order-0 entropy alone. A real codec beats
        this using LZ matches, so treat it as a sanity bound, not a target."""
        return self.entropy / 8.0


def _histogram(sample: bytes):
    """Byte histogram. NumPy where available: a pure-Python Counter over a
    64 KiB sample costs more than the zstd encode it is supposed to be
    deciding about, which made the probe the pipeline's own bottleneck."""
    if _np is not None:
        return _np.bincount(
            _np.frombuffer(sample, dtype=_np.uint8), minlength=256
        ).astype(float)
    counts = Counter(sample)
    return [float(counts.get(i, 0)) for i in range(256)]


def _entropy_from_hist(hist, n: int) -> float:
    if not n:
        return 0.0
    if _np is not None:
        nz = hist[hist > 0] / n
        return float(-(nz * _np.log2(nz)).sum())
    return -sum((c / n) * math.log2(c / n) for c in hist if c)


def shannon_entropy(data: bytes) -> float:
    """Order-0 entropy in bits/byte. Cheap, and sufficient to separate
    'already compressed' from 'worth trying' — which is the only decision it
    is asked to make."""
    if not data:
        return 0.0
    return _entropy_from_hist(_histogram(data), len(data))


def probe(data: bytes) -> Probe:
    sample = data[:PROBE_BYTES]
    magic = next(
        (name for sig, name in _INCOMPRESSIBLE_MAGIC if data.startswith(sig)), None
    )
    if sample:
        hist = _histogram(sample)
        printable = float(sum(hist[9:14]) + sum(hist[32:127]))
        ratio = printable / len(sample)
    else:
        ratio = 0.0
    head = data[:512].lstrip()
    textual = ratio > 0.90 or any(head.startswith(h) for h in _TEXTUAL_HINTS)
    return Probe(
        size=len(data),
        entropy=_entropy_from_hist(hist, len(sample)) if sample else 0.0,
        printable_ratio=ratio,
        magic=magic,
        looks_textual=textual,
    )


@dataclass(frozen=True)
class SelectionPolicy:
    """Where to sit on the ratio/latency curve.

    `fast`     — interactive uploads, hot path. zstd only.
    `balanced` — default. zstd, escalating for text.
    `archival` — cold storage. Willing to spend 100x CPU for the last 8%.
    """

    name: str = "balanced"
    max_probe_encode: int = 256 * 1024  # cap for the trial-encode escape hatch

    @property
    def archival(self) -> bool:
        return self.name == "archival"

    @property
    def fast(self) -> bool:
        return self.name == "fast"


BALANCED = SelectionPolicy("balanced")
FAST = SelectionPolicy("fast")
ARCHIVAL = SelectionPolicy("archival")


def select(
    data: bytes,
    policy: SelectionPolicy = BALANCED,
    pr: Probe | None = None,
) -> tuple[codecs.Codec, int]:
    """Return (codec, level) for this payload."""
    pr = pr or probe(data)

    # 1. Already entropy-coded. Store verbatim. The one exception worth making
    #    later is PDF/ZIP recompression via precomp-style stream rewriting,
    #    which is a different project.
    if pr.magic and pr.magic != "riff":
        return codecs.by_name("store"), 0

    # 2. High-entropy payload with no known container: encrypted, random, or
    #    a codec we don't have magic for. 7.5 bits/byte leaves ~6% headroom,
    #    which LZ will not recover on a chunk this size.
    if pr.entropy > 7.5:
        return codecs.by_name("store"), 0

    # 3. Tiny chunks: framing overhead dominates. zstd's frame is the smallest
    #    of the modern codecs and it degrades gracefully.
    if pr.size < 256:
        return codecs.by_name("zstd"), 6

    if policy.fast:
        return codecs.by_name("zstd"), 1

    if pr.looks_textual:
        if policy.archival:
            return codecs.by_name("brotli-text"), 11
        # Level 6, not 10+. Measured on a JSON corpus: zstd -6 gives 8.84x at
        # 124 MB/s, zstd -10 gives 9.00x at 51 MB/s. Paying 2.4x the CPU for
        # 1.8% more ratio is a bad trade on a live upload path.
        return codecs.by_name("zstd"), 6

    if policy.archival:
        # Binary and cold: lzma still wins on structured binary (executables,
        # uncompressed images, columnar dumps) at a brutal encode cost.
        return codecs.by_name("lzma"), 6

    return codecs.by_name("zstd"), 3


def select_empirical(
    data: bytes,
    candidates: list[tuple[str, int]] | None = None,
) -> tuple[codecs.Codec, int, bytes]:
    """Escape hatch: actually try N codecs and keep the smallest.

    Only for archival re-packing jobs where the object is written once and
    read for years. Never call this on the upload path.
    """
    candidates = candidates or [
        ("zstd-max", 19),
        ("brotli-text", 11),
        ("lzma", 6),
        ("store", 0),
    ]
    best: tuple[codecs.Codec, int, bytes] | None = None
    for name, level in candidates:
        codec = codecs.by_name(name)
        try:
            out = codec.encode(data, level)
        except Exception:  # noqa: BLE001 - a broken codec must not kill the job
            continue
        if best is None or len(out) < len(best[2]):
            best = (codec, level, out)
    assert best is not None
    return best

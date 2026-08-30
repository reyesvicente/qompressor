"""
Content-defined chunking.

Why CDC and not fixed-size blocks: fixed blocking is destroyed by insertion.
Prepend one byte and every boundary shifts, every block hash changes, and
dedup yields exactly nothing. CDC derives boundaries from a rolling hash of
the *content*, so an edit only perturbs the chunks it physically touches.

CANONICAL DEFINITION (do not change without a full re-index)
------------------------------------------------------------
* Gear hash, continuous over the whole stream. Unlike the FastCDC paper we do
  not reset the hash at each cut. Resetting makes the first ~64 bytes of every
  chunk depend on where the previous cut landed, which (a) weakens shift
  resistance at chunk starts and (b) makes the recurrence non-vectorisable.
  Keeping it continuous makes H[i] a pure function of bytes [i-63 .. i], which
  is what lets the fast path below exist at all.
* H[i] = sum(k=0..63) GEAR[data[i-k]] << k, mod 2**64.
* Boundary at absolute index i if the mask test passes; chunk length is
  i + 1 - chunk_start.
* Normalised chunking: a strict (more bits) mask applies until the chunk
  reaches avg_size, a lax mask after it. This pulls the size distribution
  toward the target instead of the fat exponential tail a single mask gives,
  cutting both manifest overhead and the count of undersized chunks that
  compress badly.
* min_size suppresses boundaries; max_size forces one.

Two implementations of the same definition ship here: a readable reference and
a vectorised fast path. tests/test_chunking.py asserts they agree byte for byte
on random and structured input. Touch one and the test tells you that you broke
the other.
"""

from __future__ import annotations

import ctypes
import random
from dataclasses import dataclass
from typing import BinaryIO, Iterator

from . import _native

__all__ = [
    "ChunkerConfig",
    "Chunk",
    "DEFAULT_CONFIG",
    "chunk_bytes",
    "chunk_stream",
    "GEAR",
    "WINDOW",
]

WINDOW = 64
_MASK64 = (1 << 64) - 1

# 256 fixed 64-bit values. The seed is frozen on purpose: boundaries must be
# byte-identical across processes, hosts and releases, or the dedup index
# silently stops matching after a deploy and the storage bill quietly doubles.
# Never regenerate this table.
_rng = random.Random(0x5EEDC0DE1337)
GEAR: tuple[int, ...] = tuple(_rng.getrandbits(64) for _ in range(256))


def _mask(bits: int) -> int:
    """Top-`bits` mask. Gear concentrates entropy in the high bits, so sample
    there; the low bits of a shift-and-add hash are close to useless."""
    return ((1 << bits) - 1) << (64 - bits)


@dataclass(frozen=True)
class ChunkerConfig:
    """Defaults are measured, not folklore.

    Chunking costs ratio, because every chunk is compressed independently and
    the codec loses cross-chunk context. Measured on a 12.8 MiB JSON event log
    (solid zstd -3 = 8.69x, gzip -6 = 8.57x), varying avg_size only:

        avg_size   ratio    dedup retained after a mid-file edit
          8 KiB    7.00x    99.9%
         16 KiB    7.96x    99.8%
         64 KiB    8.93x    99.3%    <- default
        256 KiB    9.61x    97.5%
          1 MiB    9.40x    90.9%

    8 KiB — the FastCDC paper's figure, and what most dedup literature quotes —
    gives up 20% of the ratio to buy 0.6 points of dedup you will never notice.
    64 KiB is where the ratio loss vanishes while insertion resistance is still
    effectively total. Go to 256 KiB for cold archival where dedup matters less
    than bytes; go to 8 KiB only for backup workloads with heavy small-delta
    churn, and know what it costs.
    """

    min_size: int = 16 * 1024
    avg_size: int = 64 * 1024
    max_size: int = 512 * 1024
    normalization: int = 2

    def __post_init__(self) -> None:
        if not (self.min_size < self.avg_size < self.max_size):
            raise ValueError("require min_size < avg_size < max_size")
        if self.avg_size & (self.avg_size - 1):
            raise ValueError("avg_size must be a power of two")
        if self.min_size < WINDOW:
            raise ValueError(f"min_size must be >= {WINDOW}")

    @property
    def _avg_bits(self) -> int:
        return self.avg_size.bit_length() - 1

    @property
    def mask_strict(self) -> int:
        return _mask(min(self._avg_bits + self.normalization, 40))

    @property
    def mask_lax(self) -> int:
        return _mask(max(self._avg_bits - self.normalization, 8))


DEFAULT_CONFIG = ChunkerConfig()


@dataclass(frozen=True)
class Chunk:
    offset: int
    data: bytes

    @property
    def size(self) -> int:
        return len(self.data)


# ---------------------------------------------------------------------------
# Hash generation
# ---------------------------------------------------------------------------


def _hashes_ref(data: bytes, ctx: bytes = b"") -> list[int]:
    """Reference. H[i] for each byte of `data`, with `ctx` supplying preceding
    context so a block boundary never changes the result."""
    buf = ctx[-(WINDOW - 1) :] + data
    base = len(buf) - len(data)
    out: list[int] = []
    for i in range(base, len(buf)):
        h = 0
        for k in range(min(WINDOW, i + 1)):
            h = (h + (GEAR[buf[i - k]] << k)) & _MASK64
        out.append(h)
    return out


def _hashes_fast(data: bytes, ctx: bytes = b""):
    """Vectorised. Same values as _hashes_ref, roughly two orders of magnitude
    faster.

    H[i] = sum(k<64) GEAR[b[i-k]] << k is a fixed 64-tap FIR filter over uint64
    with wraparound. Naively that is 64 passes over the array. By doubling it
    is 6:

        A1[i]  = GEAR[b[i]]
        A2[i]  = A1[i]  + (A1[i-1]  << 1)
        A4[i]  = A2[i]  + (A2[i-2]  << 2)
        ...
        A64[i] = A32[i] + (A32[i-32] << 32)

    Each step doubles the tap count, and uint64 overflow *is* the mod 2**64 we
    want, so nothing needs masking.
    """
    import numpy as np

    buf = ctx[-(WINDOW - 1) :] + data
    base = len(buf) - len(data)
    g = _GEAR_NP[np.frombuffer(buf, dtype=np.uint8)]

    span = 1
    while span < WINDOW:
        shifted = np.zeros_like(g)
        shifted[span:] = g[:-span] << np.uint64(span)
        g = g + shifted  # wraps at 2**64 == the modulus we want
        span <<= 1

    return g[base:]


try:  # numpy is a hard dependency in the image; degrade gracefully anyway
    import numpy as _np

    _GEAR_NP = _np.array(GEAR, dtype=_np.uint64)
    _HAVE_NUMPY = True
except Exception:  # pragma: no cover
    _GEAR_NP = None
    _HAVE_NUMPY = False

_GEAR_C = (ctypes.c_uint64 * 256)(*GEAR)


# ---------------------------------------------------------------------------
# Boundary scan
# ---------------------------------------------------------------------------


def _cuts_from_hashes(hashes, n: int, cfg: ChunkerConfig) -> list[int]:
    """Walk the hash array and emit chunk lengths.

    Sequential by necessity (each cut sets the next window), but per-step work
    is a binary search over precomputed candidate positions rather than a byte
    scan, so cost is O(chunks * log n) instead of O(n) in the interpreter.
    """
    strict, lax = cfg.mask_strict, cfg.mask_lax

    if _HAVE_NUMPY and not isinstance(hashes, list):
        import numpy as np

        cand_s = np.flatnonzero((hashes & np.uint64(strict)) == 0)
        cand_l = np.flatnonzero((hashes & np.uint64(lax)) == 0)
        search = np.searchsorted
    else:  # pure-python fallback
        import bisect

        cand_s = [i for i, h in enumerate(hashes) if not (h & strict)]
        cand_l = [i for i, h in enumerate(hashes) if not (h & lax)]

        def search(arr, v):  # type: ignore[misc]
            return bisect.bisect_left(arr, v)

    lengths: list[int] = []
    pos = 0
    while pos < n:
        earliest = pos + cfg.min_size
        if earliest >= n:
            lengths.append(n - pos)
            break

        normal_end = min(pos + cfg.avg_size, n)
        limit = min(pos + cfg.max_size, n)

        cut = None
        i = search(cand_s, earliest)
        if i < len(cand_s) and cand_s[i] < normal_end:
            cut = int(cand_s[i]) + 1
        else:
            j = search(cand_l, max(earliest, normal_end))
            if j < len(cand_l) and cand_l[j] < limit:
                cut = int(cand_l[j]) + 1

        if cut is None:
            cut = limit

        lengths.append(cut - pos)
        pos = cut

    return lengths


def _cuts_native(data: bytes, ctx: bytes, cfg: ChunkerConfig) -> list[int] | None:
    """Native scan. Returns None if the accelerator is not available."""
    lib = _native.load()
    if lib is None:
        return None

    n = len(data)
    cap = n // cfg.min_size + 2
    out = (ctypes.c_uint32 * cap)()
    written = lib.pp_chunk(
        data,
        n,
        ctx,
        len(ctx),
        _GEAR_C,
        ctypes.c_uint64(cfg.mask_strict),
        ctypes.c_uint64(cfg.mask_lax),
        cfg.min_size,
        cfg.avg_size,
        cfg.max_size,
        out,
        cap,
    )
    if written == ctypes.c_size_t(-1).value:  # pragma: no cover - cap is a bound
        return None
    return list(out[:written])


def _cuts(
    data: bytes, ctx: bytes, cfg: ChunkerConfig, backend: str = "auto"
) -> list[int]:
    """Chunk lengths for `data`, given `ctx` bytes of preceding context.

    Backends are ordered by speed and produce identical output by contract:
      native (~1 GB/s) -> numpy (~20 MB/s) -> pure python (~2 MB/s)
    """
    if backend in ("auto", "native"):
        lengths = _cuts_native(data, ctx, cfg)
        if lengths is not None:
            return lengths
        if backend == "native":
            raise RuntimeError("native chunker requested but libppcdc.so is missing")

    if backend in ("auto", "numpy") and _HAVE_NUMPY:
        return _cuts_from_hashes(_hashes_fast(data, ctx), len(data), cfg)

    return _cuts_from_hashes(_hashes_ref(data, ctx), len(data), cfg)


def chunk_bytes(
    data: bytes, cfg: ChunkerConfig = DEFAULT_CONFIG, backend: str = "auto"
) -> Iterator[Chunk]:
    """Chunk an in-memory buffer. `backend` pins the implementation; only tests
    should ever pass anything other than "auto"."""
    if not data:
        return
    offset = 0
    for length in _cuts(data, b"", cfg, backend):
        yield Chunk(offset=offset, data=data[offset : offset + length])
        offset += length


def chunk_stream(
    fp: BinaryIO,
    cfg: ChunkerConfig = DEFAULT_CONFIG,
    read_size: int = 8 * 1024 * 1024,
    backend: str = "auto",
) -> Iterator[Chunk]:
    """Chunk an arbitrarily large stream in bounded memory.

    Holds at most read_size + max_size bytes, so a 40 GB object costs the same
    RSS as a 40 KB one. Boundaries are identical to chunk_bytes on the same
    input: the WINDOW-1 byte carry means a read boundary never influences a
    cut. That invariant is load-bearing — if it broke, the same object would
    dedup against itself differently depending on network timing.
    """
    carry = bytearray()
    ctx = b""  # WINDOW-1 bytes immediately preceding `carry`
    offset = 0
    eof = False

    while True:
        if not eof:
            block = fp.read(read_size)
            if block:
                carry += block
                if len(carry) < cfg.max_size:
                    continue
            else:
                eof = True

        if not carry:
            return

        payload = bytes(carry)
        n = len(payload)
        cuts = _cuts(payload, ctx, cfg, backend)

        # Near EOF everything can be emitted. Otherwise hold back max_size so a
        # cut is never decided on a truncated view of the stream.
        usable = n if eof else max(0, n - cfg.max_size)

        consumed = 0
        for length in cuts:
            if not eof and consumed + length > usable:
                break
            yield Chunk(offset=offset, data=payload[consumed : consumed + length])
            offset += length
            consumed += length

        if consumed:
            ctx = payload[max(0, consumed - (WINDOW - 1)) : consumed]
            del carry[:consumed]

        if eof:
            if carry:
                yield Chunk(offset=offset, data=bytes(carry))
            return

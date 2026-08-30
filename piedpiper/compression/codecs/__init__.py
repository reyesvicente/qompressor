"""
Codec registry.

Every codec is addressed by a 1-byte id that is written into the chunk header
on disk. Ids are permanent: once a chunk is stored with id 0x02 it must decode
as zstd forever. Add codecs, never renumber them.
"""

from __future__ import annotations

import bz2
import gzip
import lzma
import zlib
from dataclasses import dataclass
from typing import Callable, Protocol

import brotli
import zstandard as zstd

__all__ = ["Codec", "CODECS", "by_id", "by_name", "encode", "decode"]


class _Compressor(Protocol):
    def __call__(self, data: bytes, level: int) -> bytes: ...


@dataclass(frozen=True)
class Codec:
    id: int
    name: str
    encode: Callable[[bytes, int], bytes]
    decode: Callable[[bytes], bytes]
    default_level: int
    # Rough single-core MB/s at default level. Used by the dispatcher's cost
    # model, not a benchmark result — recalibrate with scripts/calibrate.py.
    throughput_mbs: float


# --- store ------------------------------------------------------------------
# Not a no-op for convenience: it is the correct answer for already-compressed
# payloads (JPEG, MP4, ZIP, encrypted blobs). Spending CPU there costs time and
# usually *grows* the output.
_STORE = Codec(0x00, "store", lambda d, _l: d, lambda d: d, 0, 100_000.0)

_DEFLATE = Codec(
    0x01,
    "deflate",
    lambda d, l: zlib.compress(d, l),
    zlib.decompress,
    6,
    90.0,
)


def _zstd_encode(data: bytes, level: int) -> bytes:
    return zstd.ZstdCompressor(level=level, write_checksum=False).compress(data)


def _zstd_decode(data: bytes) -> bytes:
    return zstd.ZstdDecompressor().decompress(data)


_ZSTD = Codec(0x02, "zstd", _zstd_encode, _zstd_decode, 10, 300.0)
_ZSTD_MAX = Codec(0x03, "zstd-max", _zstd_encode, _zstd_decode, 19, 8.0)

_BROTLI = Codec(
    0x04,
    "brotli",
    lambda d, l: brotli.compress(d, quality=l),
    brotli.decompress,
    9,
    30.0,
)
_BROTLI_TEXT = Codec(
    0x05,
    "brotli-text",
    lambda d, l: brotli.compress(d, quality=l, mode=brotli.MODE_TEXT),
    brotli.decompress,
    11,
    2.0,
)

_LZMA = Codec(
    0x06,
    "lzma",
    lambda d, l: lzma.compress(d, preset=l | lzma.PRESET_EXTREME),
    lzma.decompress,
    6,
    3.0,
)
_BZIP2 = Codec(0x07, "bzip2", lambda d, l: bz2.compress(d, l), bz2.decompress, 9, 12.0)
_GZIP = Codec(
    0x08,
    "gzip",
    lambda d, l: gzip.compress(d, compresslevel=l, mtime=0),
    gzip.decompress,
    6,
    90.0,
)

# 0x80+ is reserved for dictionary-backed variants; the dictionary id is
# carried in the chunk header, so the codec itself stays stateless.
_ZSTD_DICT_ID = 0x82

CODECS: dict[int, Codec] = {
    c.id: c
    for c in (
        _STORE,
        _DEFLATE,
        _ZSTD,
        _ZSTD_MAX,
        _BROTLI,
        _BROTLI_TEXT,
        _LZMA,
        _BZIP2,
        _GZIP,
    )
}
_BY_NAME = {c.name: c for c in CODECS.values()}


def by_id(codec_id: int) -> Codec:
    try:
        return CODECS[codec_id]
    except KeyError:
        raise ValueError(f"unknown codec id 0x{codec_id:02x}") from None


def by_name(name: str) -> Codec:
    try:
        return _BY_NAME[name]
    except KeyError:
        raise ValueError(f"unknown codec {name!r}") from None


def encode(data: bytes, codec: Codec, level: int | None = None) -> bytes:
    return codec.encode(data, codec.default_level if level is None else level)


def decode(data: bytes, codec_id: int) -> bytes:
    return by_id(codec_id).decode(data)


# --- dictionary-backed zstd -------------------------------------------------
# The real force multiplier for many small, structurally similar payloads
# (JSON events, log lines, HTML fragments). A shared dictionary gives the
# window prior context it otherwise cannot have below ~1 KB, where every
# general-purpose codec is effectively blind.


def train_dictionary(samples: list[bytes], dict_size: int = 112 * 1024) -> bytes:
    usable = [s for s in samples if s]
    if len(usable) < 8:
        raise ValueError("need at least 8 non-empty samples to train")
    return zstd.train_dictionary(dict_size, usable).as_bytes()


def encode_with_dict(data: bytes, raw_dict: bytes, level: int = 10) -> bytes:
    d = zstd.ZstdCompressionDict(raw_dict)
    return zstd.ZstdCompressor(level=level, dict_data=d, write_checksum=False).compress(
        data
    )


def decode_with_dict(data: bytes, raw_dict: bytes) -> bytes:
    d = zstd.ZstdCompressionDict(raw_dict)
    return zstd.ZstdDecompressor(dict_data=d).decompress(data)


ZSTD_DICT_ID = _ZSTD_DICT_ID

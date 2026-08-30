"""
ctypes binding for the native boundary scanner.

Deliberately ctypes and not a C extension: no build-time Python headers, no
ABI pinning, no wheel per interpreter version. The .so is a leaf artefact
built once in the Docker image. If it is absent the caller silently falls back
to the vectorised NumPy path and then to pure Python — the *boundaries are
identical* in all three, so a missing .so is a performance incident, never a
correctness or dedup-index one.
"""

from __future__ import annotations

import ctypes
import os
import pathlib
import subprocess
import sys

__all__ = ["load", "build", "SO_PATH"]

HERE = pathlib.Path(__file__).parent
SRC = HERE / "ppcdc.c"

# Normally the .so sits next to this file. Local Docker is the exception: the
# compose file bind-mounts the source tree over /app, which would shadow a .so
# baked in at build time and silently drop us to the ~8 MB/s pure-Python path.
# The image therefore builds it outside /app and points here.
SO_PATH = pathlib.Path(os.environ.get("PIEDPIPER_NATIVE_SO") or HERE / "libppcdc.so")

_lib = None
_loaded = False


def build(cc: str = "cc") -> pathlib.Path:
    """Compile the accelerator. Called from the Dockerfile build stage."""
    cmd = [
        cc,
        "-O3",
        "-fPIC",
        "-shared",
        "-fno-strict-aliasing",
        "-o",
        str(SO_PATH),
        str(SRC),
    ]
    if sys.platform.startswith("linux"):
        # -march=native would be faster but the image may be built on a
        # different CPU than it runs on. x86-64-v2 is safe on anything since
        # Nehalem and is what every cloud instance provides.
        cmd.insert(1, "-march=x86-64-v2")
    subprocess.run(cmd, check=True)
    return SO_PATH


def load():
    """Return the loaded library, or None if unavailable."""
    global _lib, _loaded
    if _loaded:
        return _lib
    _loaded = True
    if not SO_PATH.exists():
        return None
    try:
        lib = ctypes.CDLL(str(SO_PATH))
        lib.pp_chunk.restype = ctypes.c_size_t
        lib.pp_chunk.argtypes = [
            ctypes.c_char_p,  # data
            ctypes.c_size_t,  # n
            ctypes.c_char_p,  # ctx
            ctypes.c_size_t,  # ctx_len
            ctypes.POINTER(ctypes.c_uint64),  # gear
            ctypes.c_uint64,  # mask_s
            ctypes.c_uint64,  # mask_l
            ctypes.c_size_t,  # min_size
            ctypes.c_size_t,  # avg_size
            ctypes.c_size_t,  # max_size
            ctypes.POINTER(ctypes.c_uint32),  # out
            ctypes.c_size_t,  # out_cap
        ]
        _lib = lib
    except OSError:
        _lib = None
    return _lib


if __name__ == "__main__":  # python -m piedpiper.compression._native
    print(build())

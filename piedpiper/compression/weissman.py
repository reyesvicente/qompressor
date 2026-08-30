"""
Weissman score.

    W = alpha * (r / r_ref) * (log(T_ref) / log(T))

where r is compression ratio, T is compression time, and _ref is a universally
agreed baseline (here: gzip -6, single-threaded, same input, same box).

Provenance, since it always comes up in review: this is a real formula, coined
by Tsachy Weissman and Vinith Misra at Stanford for the HBO show, not a
standard information-theory metric. Treat it as what it is — a single scalar
that trades ratio against log-time so you cannot win by burning a week of CPU
for another 2%. That property is genuinely useful for ranking codecs; the
absolute number means nothing.

Three things will bite you if you report it without reading this:

  * It is only comparable within one corpus on one machine. Cross-corpus
    Weissman scores are noise.
  * log(T) is degenerate at T = 1 and flips sign below it. Seconds is the
    naive unit and it is wrong: a sub-second compression lands on the floor and
    every score collapses to ~0. We measure in milliseconds, where realistic
    times are comfortably above 1, and still clamp.
  * alpha is a free scaling constant. Anyone quoting a Weissman score without
    stating alpha, the baseline and the corpus is quoting a vibe.
"""

from __future__ import annotations

import gzip
import io
import math
import time
from dataclasses import dataclass

__all__ = ["Measurement", "measure_baseline", "weissman_score"]

MIN_TIME_MS = 1.0001  # log() floor; below 1ms the score inverts


@dataclass(frozen=True)
class Measurement:
    raw_size: int
    compressed_size: int
    elapsed: float

    @property
    def ratio(self) -> float:
        return self.raw_size / self.compressed_size if self.compressed_size else 0.0

    @property
    def throughput_mbs(self) -> float:
        return (self.raw_size / 1_048_576) / self.elapsed if self.elapsed else 0.0


def measure_baseline(data: bytes, level: int = 6) -> Measurement:
    """gzip -6, the closest thing to a universal reference point."""
    started = time.perf_counter()
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", compresslevel=level, mtime=0) as fh:
        fh.write(data)
    elapsed = time.perf_counter() - started
    return Measurement(len(data), buf.tell(), elapsed)


def weissman_score(
    target: Measurement, baseline: Measurement, alpha: float = 1.0
) -> float:
    if baseline.ratio <= 0 or target.ratio <= 0:
        return 0.0
    t = max(target.elapsed * 1000.0, MIN_TIME_MS)
    t_ref = max(baseline.elapsed * 1000.0, MIN_TIME_MS)
    return alpha * (target.ratio / baseline.ratio) * (math.log(t_ref) / math.log(t))

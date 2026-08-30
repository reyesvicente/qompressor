"""One-shot CLI compressor. Useful for calibration and for proving the core
works without Postgres, Redis or a web request in the loop.

    python manage.py ppcompress path/to/file --policy archival
"""

from __future__ import annotations

import pathlib
import time

from django.core.management.base import BaseCommand

from piedpiper.compression.pipeline import MemoryStore, compress_stream, verify
from piedpiper.compression.tasks import POLICIES
from piedpiper.compression.weissman import Measurement, measure_baseline, weissman_score


class Command(BaseCommand):
    help = "Compress a file and report ratio, throughput and Weissman score."

    def add_arguments(self, parser):
        parser.add_argument("path")
        parser.add_argument("--policy", default="balanced", choices=list(POLICIES))

    def handle(self, *args, **opts):
        path = pathlib.Path(opts["path"])
        data = path.read_bytes()
        store = MemoryStore()

        started = time.perf_counter()
        with path.open("rb") as fh:
            manifest = compress_stream(fh, store, POLICIES[opts["policy"]])
        elapsed = time.perf_counter() - started

        assert verify(manifest, store), "roundtrip verification FAILED"
        target = Measurement(manifest.raw_size, store.physical_size, elapsed)
        base = measure_baseline(data)

        self.stdout.write(
            f"{path.name}  {manifest.raw_size} -> {store.physical_size} B\n"
            f"  ratio      {target.ratio:.2f}x   (gzip -6: {base.ratio:.2f}x)\n"
            f"  throughput {target.throughput_mbs:.0f} MB/s "
            f"(gzip -6: {base.throughput_mbs:.0f} MB/s)\n"
            f"  weissman   {weissman_score(target, base):.2f}\n"
            f"  chunks     {len(manifest.chunks)}  {manifest.codec_histogram()}\n"
            f"  sha256     {manifest.sha256}"
        )

#!/usr/bin/env python3
"""
Benchmark harness. Every number in the README comes from this script.

    docker compose -f docker-compose.local.yml run --rm django \
        python scripts/benchmark.py

Reports, per corpus: ratio, throughput and Weissman score against gzip -6,
plus the dedup and dictionary results that a flat codec comparison hides.
"""

from __future__ import annotations

import io
import os
import pathlib
import random
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from piedpiper.compression import codecs  # noqa: E402
from piedpiper.compression.chunking import chunk_bytes  # noqa: E402
from piedpiper.compression.dispatch import ARCHIVAL, BALANCED, FAST  # noqa: E402
from piedpiper.compression.pipeline import (  # noqa: E402
    MemoryStore,
    compress_stream,
    verify,
)
from piedpiper.compression.weissman import (  # noqa: E402
    Measurement,
    measure_baseline,
    weissman_score,
)


# ---------------------------------------------------------------------------
# Corpora
# ---------------------------------------------------------------------------


def json_events(n: int, salt: int = 0) -> bytes:
    rng = random.Random(42 + salt)
    paths = ["/", "/products", "/products/%d", "/cart", "/checkout", "/account"]
    return b"".join(
        (
            '{"id":%d,"user_id":%d,"event":"page_view","ts":"2026-08-%02dT%02d:%02d:%02dZ",'
            '"path":"%s","referrer":"https://google.com/","ua":"Mozilla/5.0 (X11; Linux '
            'x86_64) AppleWebKit/537.36","session":"%s","ms":%d}\n'
            % (
                i + salt,
                rng.randrange(50_000),
                (i % 28) + 1,
                i % 24,
                i % 60,
                (i * 7) % 60,
                (paths[i % len(paths)] % i if "%d" in paths[i % len(paths)] else paths[i % len(paths)]),
                "%016x" % rng.getrandbits(64),
                rng.randrange(5, 900),
            )
        ).encode()
        for i in range(n)
    )


def source_code(limit: int) -> bytes:
    """Real Python source from the stdlib: the canonical 'compressible but not
    trivially repetitive' corpus."""
    out, total = [], 0
    root = pathlib.Path(sys.prefix) / "lib"
    for path in sorted(root.rglob("*.py")):
        try:
            blob = path.read_bytes()
        except OSError:
            continue
        out.append(blob)
        total += len(blob)
        if total >= limit:
            break
    return b"".join(out)[:limit]


def incompressible(n: int) -> bytes:
    return random.Random(7).randbytes(n)


def small_docs(count: int) -> list[bytes]:
    rng = random.Random(3)
    return [
        (
            '{"order_id":"%s","customer":{"id":%d,"tier":"%s"},"items":[{"sku":"SKU-%05d",'
            '"qty":%d,"price_cents":%d}],"currency":"PHP","status":"%s"}'
            % (
                "%012x" % rng.getrandbits(48),
                rng.randrange(200_000),
                rng.choice(["free", "plus", "pro"]),
                rng.randrange(99999),
                rng.randrange(1, 5),
                rng.randrange(9900, 999900),
                rng.choice(["paid", "pending", "shipped", "refunded"]),
            )
        ).encode()
        for _ in range(count)
    ]


# ---------------------------------------------------------------------------


def run_pipeline(data: bytes, policy) -> tuple[Measurement, dict]:
    store = MemoryStore()
    started = time.perf_counter()
    manifest = compress_stream(io.BytesIO(data), store, policy)
    elapsed = time.perf_counter() - started
    assert verify(manifest, store), "ROUNDTRIP FAILED"
    return (
        Measurement(manifest.raw_size, store.physical_size, elapsed),
        manifest.codec_histogram(),
    )


def hr(title: str = "") -> None:
    print(f"\n{title}\n" + "-" * 78 if title else "-" * 78)


def bench_corpora() -> None:
    corpora = [
        ("json events   ", json_events(120_000)),
        ("python source ", source_code(24 * 1024 * 1024)),
        ("random bytes  ", incompressible(16 * 1024 * 1024)),
    ]
    hr("CORPUS BENCHMARK  (baseline: gzip -6, single core)")
    print(
        f"{'corpus':<15}{'MiB':>7}{'mode':>10}{'ratio':>9}{'MB/s':>9}"
        f"{'weissman':>10}  codecs chosen"
    )
    for name, data in corpora:
        base = measure_baseline(data)
        print(
            f"{name:<15}{len(data)/1048576:>7.1f}{'gzip -6':>10}"
            f"{base.ratio:>8.2f}x{base.throughput_mbs:>9.0f}{1.00:>10.2f}"
        )
        for label, policy in (
            ("fast", FAST),
            ("balanced", BALANCED),
            ("archival", ARCHIVAL),
        ):
            m, hist = run_pipeline(data, policy)
            w = weissman_score(m, base)
            top = ", ".join(
                f"{k}:{v}" for k, v in sorted(hist.items(), key=lambda kv: -kv[1])[:3]
            )
            print(
                f"{'':<15}{'':>7}{label:>10}{m.ratio:>8.2f}x"
                f"{m.throughput_mbs:>9.0f}{w:>10.2f}  {top}"
            )


def bench_dedup() -> None:
    hr("DEDUP  (what a flat codec comparison cannot show)")
    v1 = json_events(80_000)
    store = MemoryStore()

    m1 = compress_stream(io.BytesIO(v1), store, BALANCED)
    print(
        f"  v1 upload          {m1.raw_size/1048576:6.1f} MiB in -> "
        f"{m1.stored_size/1048576:6.2f} MiB written   ratio {m1.marginal_ratio:6.2f}x"
    )

    # An edit in the middle: the realistic case for logs, backups, CI artefacts.
    cut = len(v1) // 2
    v2 = v1[:cut] + json_events(400, salt=10**6) + v1[cut:]
    m2 = compress_stream(io.BytesIO(v2), store, BALANCED)
    print(
        f"  v2 (edit in place) {m2.raw_size/1048576:6.1f} MiB in -> "
        f"{m2.stored_size/1024:6.1f} KiB written   ratio {m2.marginal_ratio:8.0f}x"
        f"   {m2.dedup_rate*100:.1f}% chunks deduped"
    )

    m3 = compress_stream(io.BytesIO(v1), store, BALANCED)
    print(
        f"  v3 (re-upload v1)  {m3.raw_size/1048576:6.1f} MiB in -> "
        f"{m3.stored_size:6d} B written     {m3.dedup_rate*100:.0f}% chunks deduped"
    )
    assert verify(m2, store) and verify(m3, store)

    # Insertion resistance is the whole reason for CDC. Show the counterfactual.
    from piedpiper.compression.pipeline import content_hash

    a = {content_hash(c.data) for c in chunk_bytes(v1)}
    b = {content_hash(c.data) for c in chunk_bytes(b"X" + v1)}
    fixed_a = {content_hash(v1[i : i + 8192]) for i in range(0, len(v1), 8192)}
    x = b"X" + v1
    fixed_b = {content_hash(x[i : i + 8192]) for i in range(0, len(x), 8192)}
    print(
        f"\n  1-byte prepend, chunks preserved:  CDC {100*len(a&b)/len(a):5.1f}%"
        f"   fixed 8 KiB blocks {100*len(fixed_a&fixed_b)/len(fixed_a):5.1f}%"
    )


def bench_dictionary() -> None:
    hr("TRAINED DICTIONARY  (small-payload regime, where codecs go blind)")
    docs = small_docs(20_000)
    train, test = docs[:4_000], docs[4_000:]
    raw = sum(len(d) for d in test)

    started = time.perf_counter()
    dictionary = codecs.train_dictionary(train, dict_size=48 * 1024)
    train_time = time.perf_counter() - started

    plain = sum(len(codecs.encode(d, codecs.by_name("zstd"), 10)) for d in test)
    withd = sum(len(codecs.encode_with_dict(d, dictionary, 10)) for d in test)
    gz = sum(len(codecs.encode(d, codecs.by_name("gzip"), 6)) for d in test)

    n = len(test)
    print(f"  {n} docs, mean {raw/n:.0f} B, dictionary trained in {train_time:.2f}s")
    print(f"  gzip -6            {gz/n:7.1f} B/doc   {raw/gz:5.2f}x")
    print(f"  zstd -10           {plain/n:7.1f} B/doc   {raw/plain:5.2f}x")
    print(
        f"  zstd -10 + dict    {withd/n:7.1f} B/doc   {raw/withd:5.2f}x"
        f"   <- {plain/withd:.1f}x better than dictionaryless zstd"
    )
    assert codecs.decode_with_dict(
        codecs.encode_with_dict(test[0], dictionary, 10), dictionary
    ) == test[0]


def bench_chunker() -> None:
    hr("CHUNKER BACKENDS  (identical boundaries, by contract)")
    data = json_events(200_000)
    for backend in ("native", "numpy", "python"):
        payload = data if backend == "native" else data[: 4 << 20]
        try:
            started = time.perf_counter()
            count = sum(1 for _ in chunk_bytes(payload, backend=backend))
            elapsed = time.perf_counter() - started
        except RuntimeError as exc:
            print(f"  {backend:<8} unavailable: {exc}")
            continue
        print(
            f"  {backend:<8} {(len(payload)/1048576)/elapsed:8.0f} MB/s"
            f"   ({count} chunks over {len(payload)/1048576:.1f} MiB)"
        )


if __name__ == "__main__":
    print(f"pied piper benchmark  |  python {sys.version.split()[0]}  |  cores={os.cpu_count()}")
    bench_corpora()
    bench_dedup()
    bench_dictionary()
    bench_chunker()
    print()

"""
Compression settings.

Kept in its own module and imported from base.py rather than pasted into it —
the values here are operationally load-bearing and reviewers should see them
change in isolation, not buried in a 300-line settings diff.

In config/settings/base.py:

    LOCAL_APPS = [
        "piedpiper.users",
        "piedpiper.compression",
    ]

    ...

    from .compression import *  # noqa: F401,F403  (at the END of base.py)
"""

from __future__ import annotations

import environ

env = environ.Env()

# --- storage ---------------------------------------------------------------

# Where in-flight uploads land. Local disk, always: staging bytes are written
# once, read once and deleted, so paying S3 PUT costs for them is pure waste.
PIEDPIPER_STAGING_ROOT = env("PIEDPIPER_STAGING_ROOT", default="/data/staging")

# "filesystem" | "s3". Filesystem is correct up to roughly a single node's
# disk; past that, or the moment you want more than one worker host, move to
# s3 and keep the same code path.
PIEDPIPER_CAS_BACKEND = env("PIEDPIPER_CAS_BACKEND", default="filesystem")
PIEDPIPER_CAS_ROOT = env("PIEDPIPER_CAS_ROOT", default="/data/cas")
PIEDPIPER_CAS_BUCKET = env("PIEDPIPER_CAS_BUCKET", default="")
PIEDPIPER_CAS_PREFIX = env("PIEDPIPER_CAS_PREFIX", default="chunks/")

# --- chunker ---------------------------------------------------------------
#
# CHANGING THESE INVALIDATES DEDUP AGAINST EVERYTHING ALREADY STORED.
# Existing objects stay readable — chunks are self-describing — but new
# uploads will not match old chunks, so the store grows until the old
# generation ages out. Treat a change here as a migration, not a tuning knob.
#
# Defaults are measured (scripts/benchmark.py), not inherited from the paper:
# 64 KiB gives solid-file ratio while keeping 99%+ insertion resistance.
PIEDPIPER_CHUNK_MIN = env.int("PIEDPIPER_CHUNK_MIN", default=16 * 1024)
PIEDPIPER_CHUNK_AVG = env.int("PIEDPIPER_CHUNK_AVG", default=64 * 1024)
PIEDPIPER_CHUNK_MAX = env.int("PIEDPIPER_CHUNK_MAX", default=512 * 1024)

# --- ingest ----------------------------------------------------------------

PIEDPIPER_DEFAULT_POLICY = env("PIEDPIPER_DEFAULT_POLICY", default="balanced")

# Uploads are staged to disk, never buffered in memory. Set the in-memory
# threshold to 0 so Django never tries to hold a large body in RAM.
FILE_UPLOAD_MAX_MEMORY_SIZE = 0
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024

# --- celery ----------------------------------------------------------------

CELERY_TASK_ROUTES = {
    "piedpiper.compression.tasks.ingest_blob": {"queue": "compression"},
    "piedpiper.compression.tasks.train_dictionary": {"queue": "compression"},
    "piedpiper.compression.tasks.collect_garbage": {"queue": "maintenance"},
    "piedpiper.compression.tasks.report_savings": {"queue": "maintenance"},
}

# An archival encode of a large object genuinely takes minutes. The soft limit
# gives the task a chance to raise and mark the Blob failed before the hard
# limit kills the worker and leaves the row stuck in "running".
CELERY_TASK_SOFT_TIME_LIMIT = 20 * 60
CELERY_TASK_TIME_LIMIT = 25 * 60

CELERY_BEAT_SCHEDULE = {
    "collect-garbage": {
        "task": "piedpiper.compression.tasks.collect_garbage",
        "schedule": 15 * 60,
    },
    "report-savings": {
        "task": "piedpiper.compression.tasks.report_savings",
        "schedule": 60 * 60,
    },
}

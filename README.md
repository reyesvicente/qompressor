# Pied Piper

Content-aware, deduplicating compression service. Upload a file once; every
duplicate chunk across your entire corpus — past, present, and future — is
stored exactly one byte, ever, with a byte-for-byte reconstruction guarantee.

[![Built with Cookiecutter Django](https://img.shields.io/badge/built%20with-Cookiecutter%20Django-ff69b4.svg?logo=cookiecutter)](https://github.com/cookiecutter/cookiecutter-django/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

License: MIT

## What it does

```
stream -> content-defined chunking -> blake2b digest -> dedup gate -> codec dispatch -> encode -> CAS
```

- **Content-defined chunking (CDC).** Objects are split on a continuous Gear
  hash of their content, not fixed-size blocks — so inserting one byte
  upstream only perturbs the chunks it physically touches, instead of
  shifting every boundary after it and destroying dedup.
- **Global, content-addressed dedup.** Every chunk is keyed by digest, once,
  across every object and every tenant. Refcounts make garbage collection
  safe without locking the hot path.
- **Codec dispatch, not one-size-fits-all.** Magic bytes, Shannon entropy,
  and printable ratio — all measured on a bounded sample — decide the codec
  per chunk before any real CPU is spent, so already-compressed or
  high-entropy payloads don't get re-squeezed for nothing.
- **Trained, per-corpus dictionaries.** Small, repetitive records (the case
  generic codecs handle worst) compress far better against a zstd
  dictionary trained on real samples from that corpus.
- **A policy per workload.** `fast`, `balanced`, or `archival` — pick the
  point on the ratio-vs-time curve that fits the object, not a single global
  setting.
- **Weissman-scored codec selection.** Ratio traded against log-time on a
  fixed baseline, so a codec can't win by burning a week of CPU for another
  two percent.
- **Async by default.** Uploads are staged and handed to a Celery worker;
  the request never holds a gunicorn worker open for a multi-GB encode.
  Deletes decrement refcounts inline and let a scheduled sweep reclaim
  bytes, so the hottest table in the system never takes a long lock.

## Stack

**Backend** — Django 6 + Django REST Framework, PostgreSQL, Celery + Redis,
django-allauth (token auth + password reset / email verification), a
boto3-backed content-addressed chunk store for production (S3-compatible:
S3, Spaces, R2, MinIO), a native C content-defined chunker (`ppcdc.c`) with
a pure-Python/NumPy fallback.

**Frontend** (`frontend/`) — React 19 + TypeScript on Vite, styled with the
[ice-ds](https://www.npmjs.com/package/ice-ds) component library, talking to
the API over token auth via axios.

## Project layout

```
piedpiper/
├── config/                  # Django settings, root URLconf, Celery app
├── piedpiper/
│   ├── compression/         # the actual product: models, pipeline, API, tasks
│   │   ├── _native/         # ppcdc.c — the fast-path chunker
│   │   ├── chunking.py      # content-defined chunking (Gear hash)
│   │   ├── dispatch.py      # codec selection (entropy / magic bytes / text)
│   │   ├── pipeline.py      # stream -> chunk -> dedup -> encode -> CAS
│   │   ├── storage.py       # staging vs. content-addressed store
│   │   ├── tasks.py         # ingest, garbage collection, dictionary training
│   │   ├── weissman.py      # the scoring formula
│   │   └── api/             # BlobViewSet: upload / download / stats
│   └── users/                # custom user model + registration/reset API
└── frontend/                 # React SPA (see Stack above)
```

## Getting started

The supported local workflow runs everything through Docker Compose via
[`just`](https://github.com/casey/just):

```bash
just build
just up
just manage migrate
just manage createsuperuser
```

- App: <http://localhost:8000>
- API docs (Swagger): <http://localhost:8000/api/docs/>
- Mailpit (catches local emails — password reset, email confirmation):
  <http://127.0.0.1:8025>
- Flower (Celery monitoring): <http://localhost:5555>

Run the frontend separately (it isn't yet a compose service):

```bash
cd frontend
npm install
cp .env.example .env   # VITE_API_URL, defaults to http://localhost:8000
npm run dev
```

- App: <http://localhost:5173>

### Setting up users

- Sign up from the frontend (`/signup`) or `POST /api/auth/register/`. A
  confirmation email is sent via Mailpit in dev; nothing is gated on
  verifying it yet.
- For a superuser: `just manage createsuperuser`.

### Native chunker

The C chunker (`piedpiper/compression/_native/ppcdc.c`) must be built
**outside** the bind-mounted source tree — the local compose setup mounts
your working copy over `/app`, which would otherwise shadow the compiled
`.so` and silently fall back to the pure-Python path (measured ~750 MB/s
native vs. ~8 MB/s pure Python). It's built into the image at
`/opt/piedpiper/libppcdc.so` and located via the `PIEDPIPER_NATIVE_SO` env
var.

## API

All endpoints are namespaced under `/api/`. Token auth
(`Authorization: Token <key>`) unless noted.

| Method | Endpoint                          | Description                              |
| ------ | ---------------------------------- | ----------------------------------------- |
| POST   | `/auth/register/`                  | Create an account, returns a token        |
| POST   | `/auth-token/`                     | Log in, returns a token                   |
| POST   | `/auth/password/reset/`            | Request a password reset email            |
| POST   | `/auth/password/reset/confirm/`    | Set a new password from the emailed key   |
| POST   | `/auth/email/confirm/`             | Confirm an email address from its key     |
| GET    | `/users/me/`                       | Current user                              |
| GET    | `/blobs/`                          | List your objects                         |
| POST   | `/blobs/upload/`                   | Upload a file (multipart)                 |
| GET    | `/blobs/{id}/`                     | Object detail (status, ratio, dedup rate) |
| GET    | `/blobs/{id}/download/`            | Stream the reassembled original           |
| DELETE | `/blobs/{id}/`                     | Release the object's chunk claims         |
| GET    | `/blobs/stats/`                    | Aggregate logical/physical bytes, ratio   |

Full schema: `/api/schema/`, browsable docs: `/api/docs/`.

## Testing

The compression pipeline (`chunking.py`, `dispatch.py`, `pipeline.py`,
`weissman.py`) is pure Python with no Django import, so its 38-case core
suite runs without a database:

```bash
uv run pytest piedpiper/compression/tests/test_core.py
```

Full suite, coverage, and type checks:

```bash
just pytest
uv run coverage run -m pytest && uv run coverage html
uv run mypy piedpiper
```

## Deployment

See the [cookiecutter-django Docker deployment
docs](https://cookiecutter-django.readthedocs.io/en/latest/3-deployment/deployment-with-docker.html).
S3 storage config lives in `config/settings/production.py`; the frontend
builds to static assets via `npm run build`.

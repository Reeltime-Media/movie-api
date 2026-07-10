# Movies API

FastAPI backend for Reeltime Media — auth, catalog, playback, payments, and
subscriptions. Postgres is hosted on Supabase (used only as a database; auth
is fully custom, not Supabase Auth).

## Stack

- FastAPI + Uvicorn (async)
- SQLAlchemy 2.0 (async) + asyncpg, migrations via Alembic
- Postgres on Supabase (session pooler)
- Cloudflare R2 for media storage
- Baray for payments, Resend for transactional email
- JWT auth (PyJWT + passlib/bcrypt), Google Sign-In

## Prerequisites

- Python 3.12
- A Supabase project (Postgres) — or any Postgres instance
- Docker + Docker Compose (optional, for containerized runs)

## Setup

```bash
git clone <repo-url>
cd movie-api

python3.12 -m venv env
source env/bin/activate
pip install -r requirements.txt

cp .env.example .env
```

Fill in `.env`. At minimum you need:

- `SECRET_KEY` — any long random string
- `DATABASE_URL` / `POOLER_DATABASE_URL` — from your Supabase project settings
  (prefer the pooler URL; the direct `db.*` host is often IPv6-only and
  unreachable from Docker/local networks)
- `R2_*` — Cloudflare R2 bucket + credentials (required for media uploads;
  the API will still boot without them, but upload/transcode routes will fail)

Everything else (`BARAY_*`, `GOOGLE_CLIENT_ID`, `RESEND_*`,
`TRANSCODE_*`) is optional for local development — those features simply
no-op or return a clear error if unconfigured. See `.env.example` for the
full list with inline comments.

## Running locally

### Directly with Uvicorn

```bash
alembic upgrade head          # apply DB migrations
uvicorn app.main:app --reload --port 8000
```

The API is at `http://localhost:8000`. Interactive docs (`/docs`, `/redoc`)
are only mounted when `DEBUG=true` in `.env`.

### With Docker Compose

```bash
docker compose up --build api
```

This runs migrations automatically on container start (see
`scripts/docker-entrypoint.sh`) before launching Uvicorn with `--reload`.

## Database migrations

Migrations live in `alembic/versions/`.

```bash
alembic upgrade head                              # apply all pending migrations
alembic revision -m "add some_table"               # create a new migration
alembic downgrade -1                                # roll back one migration
```

Run Alembic from your Mac / host machine against `POOLER_DATABASE_URL`
(session mode, port 5432) — the direct Supabase host frequently times out
outside of Supabase's own network.

## Seeding sample data

Local/bootstrap only — never run these against production with default
values.

```bash
ADMIN_SEED_EMAIL=you@example.com ADMIN_SEED_PASSWORD='strong-password' python seed_admin.py
python seed_movies.py
python seed_series.py
python seed_subscription_plans.py
python seed_promotion_banners.py
```

All seed scripts are idempotent — safe to re-run.

## Tests

```bash
pytest -q
```

Also runs in CI on every push/PR to `main` (see `.github/workflows/deploy.yml`).

## Deployment

`.github/workflows/deploy.yml` builds and pushes a Docker image to GHCR on
every push to `main`, then deploys to an EC2 host over SSH via
`docker compose pull && docker compose up -d api`. Requires
`EC2_HOST`, `EC2_USER`, `EC2_SSH_KEY`, `GHCR_PAT`, and `DEPLOY_DIR` as repo
secrets.

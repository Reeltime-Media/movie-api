#!/bin/sh
# Recover when the DB already has schema but alembic_version is empty or far behind.
# Prefer `alembic upgrade head` when the version table is already correct.
#
# Uses POOLER_DATABASE_URL from movie-api/.env (direct db.* host often fails on macOS).
set -e
cd "$(dirname "$0")/.."

echo "Using pooler URL from .env for migrations (alembic_database_url)..."

current="$(alembic current 2>/dev/null | awk '{print $1; exit}')"
if [ -z "$current" ]; then
  echo "No alembic_version row — stamping baseline at 0003 (legacy tables already exist)..."
  alembic stamp 0003
else
  echo "Current revision: $current (not re-stamping)"
fi

echo "Applying pending migrations..."
alembic upgrade head

echo "Done. Current revision:"
alembic current

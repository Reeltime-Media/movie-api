#!/bin/sh
# Use when the DB already has tables from 0001–0003 but alembic_version is empty.
# Marks those migrations as applied, then runs only newer migrations (e.g. 0004).
#
# Uses POOLER_DATABASE_URL from movie-api/.env (direct db.* host often fails on macOS).
set -e
cd "$(dirname "$0")/.."

echo "Using pooler URL from .env for migrations (alembic_database_url)..."

echo "Stamping alembic baseline at 0003 (schema already exists)..."
alembic stamp 0003

echo "Applying pending migrations..."
alembic upgrade head

echo "Done. Current revision:"
alembic current

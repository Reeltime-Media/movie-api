#!/bin/sh
set -e

echo "Running database migrations..."

if ! alembic upgrade head 2>/tmp/alembic-migrate.err; then
  if grep -qE 'relation "users" already exists|DuplicateTableError.*users' /tmp/alembic-migrate.err; then
    echo "Existing schema detected without alembic_version — stamping baseline at 0003..."
    alembic stamp 0003
    alembic upgrade head
  else
    cat /tmp/alembic-migrate.err >&2
    exit 1
  fi
fi

echo "Starting API..."
exec "$@"

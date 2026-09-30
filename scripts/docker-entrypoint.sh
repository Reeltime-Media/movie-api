#!/bin/sh
set -e

echo "Running database migrations..."

if ! alembic upgrade head 2>/tmp/alembic-migrate.err; then
  if grep -qE 'relation "users" already exists|DuplicateTableError.*users' /tmp/alembic-migrate.err; then
    echo "Existing schema detected without alembic_version — stamping baseline at 0003..."
    alembic stamp 0003
    alembic upgrade head

  elif grep -qE "Can't locate revision identified by" /tmp/alembic-migrate.err; then
    echo "ERROR: DB alembic_version points at an unknown revision." >&2
    echo "Do not auto-stamp — fix manually (alembic history / stamp), then redeploy." >&2
    cat /tmp/alembic-migrate.err >&2
    exit 1

  elif grep -qE 'relation "genres" already exists' /tmp/alembic-migrate.err; then
    echo "genres table already exists — stamping 0015 and continuing..."
    alembic stamp 0015
    alembic upgrade head

  elif grep -qE 'relation "ratings" already exists' /tmp/alembic-migrate.err; then
    echo "ratings table already exists — stamping 0039 and continuing..."
    alembic stamp 0039
    alembic upgrade head

  elif grep -qE 'relation "device_pairing_codes" already exists' /tmp/alembic-migrate.err; then
    echo "device_pairing_codes table already exists — stamping 0041 and continuing..."
    alembic stamp 0041
    alembic upgrade head
  else
    cat /tmp/alembic-migrate.err >&2
    exit 1
  fi
fi

echo "Starting API..."
exec "$@"

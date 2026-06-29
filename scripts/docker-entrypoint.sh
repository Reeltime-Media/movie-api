#!/bin/sh
set -e

echo "Running database migrations..."

if ! alembic upgrade head 2>/tmp/alembic-migrate.err; then
  if grep -qE 'relation "users" already exists|DuplicateTableError.*users' /tmp/alembic-migrate.err; then
    echo "Existing schema detected without alembic_version — stamping baseline at 0003..."
    alembic stamp 0003
    alembic upgrade head

  elif grep -qE "Can't locate revision identified by" /tmp/alembic-migrate.err; then
    echo "DB has an unknown revision — force-resetting alembic_version to current head (0014)..."
    python3 - <<'PYEOF'
import os, re, sys

raw = os.environ.get("POOLER_DATABASE_URL") or os.environ.get("DATABASE_URL", "")
# psycopg2 needs plain postgresql://, not postgresql+asyncpg://
url = re.sub(r'\+asyncpg', '', raw)

import psycopg2
try:
    conn = psycopg2.connect(url)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("UPDATE alembic_version SET version_num = '0014'")
    if cur.rowcount == 0:
        cur.execute("INSERT INTO alembic_version (version_num) VALUES ('0014')")
    cur.close()
    conn.close()
    print("alembic_version reset to 0014")
except Exception as e:
    print(f"ERROR resetting alembic_version: {e}", file=sys.stderr)
    sys.exit(1)
PYEOF
    alembic upgrade head

  elif grep -qE 'relation "genres" already exists' /tmp/alembic-migrate.err; then
    echo "genres table already exists — stamping 0015 and continuing..."
    alembic stamp 0015
    alembic upgrade head
  else
    cat /tmp/alembic-migrate.err >&2
    exit 1
  fi
fi

echo "Starting API..."
exec "$@"

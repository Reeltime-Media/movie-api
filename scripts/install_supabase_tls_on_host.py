#!/usr/bin/env python3
"""Install Supabase CA bundle + wire DATABASE_SSL_* on the API host."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

API_DIR = Path("/home/thychanna17_gmail_com/movie/movie-api")
ENV_PATH = API_DIR / ".env"
CERT_DIR = API_DIR / "certs"
BUNDLE_PATH = CERT_DIR / "supabase-ca-bundle.pem"


def env_value(key: str) -> str:
    for line in ENV_PATH.read_text().splitlines():
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].strip().strip("\"'")
    return ""


def upsert_env(key: str, value: str) -> None:
    lines = ENV_PATH.read_text().splitlines()
    out: list[str] = []
    found = False
    for line in lines:
        if line.startswith(f"{key}="):
            out.append(f"{key}={value}")
            found = True
        else:
            out.append(line)
    if not found:
        if out and out[-1].strip():
            out.append("")
        out.append(f"{key}={value}")
    ENV_PATH.write_text("\n".join(out) + "\n")


def extract_certs(raw: str) -> list[str]:
    return re.findall(
        r"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----",
        raw,
        flags=re.S,
    )


def main() -> int:
    pooler = env_value("POOLER_DATABASE_URL") or env_value("DATABASE_URL")
    if not pooler:
        print("No DATABASE_URL/POOLER_DATABASE_URL in .env", file=sys.stderr)
        return 1
    norm = pooler.replace("postgresql+asyncpg://", "postgresql://", 1)
    parsed = urlparse(norm)
    host = parsed.hostname or ""
    port = parsed.port or 5432
    print(f"pooler_host={host} port={port}")

    raw = subprocess.check_output(
        [
            "openssl",
            "s_client",
            "-starttls",
            "postgres",
            "-connect",
            f"{host}:{port}",
            "-showcerts",
        ],
        input=b"",
        stderr=subprocess.DEVNULL,
    ).decode("utf-8", errors="replace")

    certs = extract_certs(raw)
    print(f"certs_in_chain={len(certs)}")
    if not certs:
        print("No certificates extracted", file=sys.stderr)
        return 1

    for i, cert in enumerate(certs):
        tmp = Path(f"/tmp/supabase-cert-{i}.pem")
        tmp.write_text(cert + "\n")
        info = subprocess.check_output(
            ["openssl", "x509", "-in", str(tmp), "-noout", "-subject", "-issuer"],
            text=True,
        )
        print(f"[{i}]\n{info}")

    # Trust store = intermediates + roots (skip leaf).
    ca_parts = certs[1:] if len(certs) > 1 else certs
    CERT_DIR.mkdir(parents=True, exist_ok=True)
    BUNDLE_PATH.write_text("\n".join(ca_parts) + "\n")
    BUNDLE_PATH.chmod(0o644)
    print(f"wrote {BUNDLE_PATH} bytes={BUNDLE_PATH.stat().st_size}")

    # Container sees certs at /app/certs/... because image WORKDIR is /app and we
    # must mount or bake the cert. Prefer host path mounted into container.
    upsert_env("DATABASE_SSL_ROOT_CERT", "/app/certs/supabase-ca-bundle.pem")
    upsert_env("DATABASE_SSL_ALLOW_INSECURE", "false")
    print("env updated: DATABASE_SSL_ROOT_CERT=/app/certs/supabase-ca-bundle.pem")
    print("env updated: DATABASE_SSL_ALLOW_INSECURE=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# Pin bookworm — python:3.12-slim tracks Debian trixie with more scanner noise.
FROM python:3.12-slim-bookworm

WORKDIR /app

# Wheels cover asyncpg/psycopg2-binary; gcc/libpq-dev only added build-time CVE surface.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates libjpeg62-turbo zlib1g \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir --upgrade "pip>=26.1.2" \
    && groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --home /app --shell /usr/sbin/nologin app

COPY requirements.txt requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock

COPY . .

RUN chmod +x scripts/docker-entrypoint.sh \
    && chown -R app:app /app

USER app

ENTRYPOINT ["/app/scripts/docker-entrypoint.sh"]
# --loop asyncio: uvloop + asyncpg SSL to Supabase pooler can raise ConnectionResetError
# FORWARDED_ALLOW_IPS: trust only loopback + private Docker/bridge ranges by default.
# Never use "*" in production — spoofable X-Forwarded-For weakens SlowAPI IP limits.
# Override with the exact load-balancer CIDRs when the edge is not on those networks.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --loop asyncio --proxy-headers --forwarded-allow-ips \"${FORWARDED_ALLOW_IPS:-127.0.0.1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16}\" --workers 2"]

# Pin bookworm — python:3.12-slim tracks Debian trixie with more scanner noise.
FROM python:3.12-slim-bookworm

WORKDIR /app

# Wheels cover asyncpg/psycopg2-binary; gcc/libpq-dev only added build-time CVE surface.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir --upgrade "pip>=26.1.2"

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN chmod +x scripts/docker-entrypoint.sh

ENTRYPOINT ["/app/scripts/docker-entrypoint.sh"]
# --loop asyncio: uvloop + asyncpg SSL to Supabase pooler can raise ConnectionResetError
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--loop", "asyncio"]

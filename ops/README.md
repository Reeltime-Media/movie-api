# Ops alerts

Every production error ends up in the Telegram alerts group, through one relay.

| Source | Reports | Path |
|---|---|---|
| GCP uptime checks | api / website / admin / live TV unreachable, TLS errors | Cloud Monitoring policy "Site down" → webhook → relay `/gcp` |
| `watchdog/` on each VM | container crashes (with last log lines), OOM kills, unhealthy containers, disk / memory / CPU, expected containers not running, VM restarts | Docker events + checks every minute → relay `/event` |
| movie-api | unhandled exceptions, ERROR logs | `app/services/error_alerts.py` → relay `/event` |
| movie-client, movie-admin | server errors (render, route handlers, server actions, proxy) | `instrumentation.ts` → relay `/event` |

The relay runs outside the VMs, so "site down" alerts still arrive when a VM is down.
It sends a repeated error at most once per 10 minutes (the next message counts the repeats)
and always sends recoveries.

## Relay (`alert_relay/`)

Cloud Run service `reeltime-alerts` in `asia-southeast1`:
https://reeltime-alerts-377818572638.asia-southeast1.run.app

- Secret Manager: `alert-relay-bot-token`, `alert-relay-token` (callers send it as
  `Authorization: Bearer …`), `alert-relay-gcp-webhook-token` (in the notification
  channel URL). `TELEGRAM_CHAT_ID` is a plain env var.
- Runs as `alert-relay@…` with access to those secrets only; `--max-instances 1` keeps
  dedup state in one place.

Redeploy after a code change (other settings are kept):

```sh
cd ops/alert_relay
TAG=$(cat main.py requirements.txt Dockerfile | sha256sum | cut -c1-12)
IMG=asia-southeast1-docker.pkg.dev/project-cad9b658-276b-47e1-adc/ops/alert-relay:$TAG
docker build -t "$IMG" . && docker push "$IMG"
gcloud run deploy reeltime-alerts --region asia-southeast1 --image "$IMG"
```

## Watchdog (`watchdog/`)

Runs as container `watchdog` on `movie-backend` and `movie-transcoder`:

```sh
docker build -t reeltime-watchdog ~/watchdog
docker run -d --name watchdog --restart unless-stopped --memory 64m \
  -v /var/run/docker.sock:/var/run/docker.sock:ro \
  --env-file ~/watchdog.env reeltime-watchdog
```

`~/watchdog.env`: `RELAY_URL`, `RELAY_TOKEN`, `HOST_LABEL`, `WATCH_CONTAINERS`
(comma separated). Thresholds: `DISK_ALERT_PERCENT` (85), `MEM_ALERT_PERCENT` (90),
`LOAD_ALERT_PER_CPU` (2.0).

## Callers

movie-api `.env` and the Vercel projects movie-client / movie-admin (production):
`ALERT_RELAY_URL` and `ALERT_RELAY_TOKEN` (the value of secret `alert-relay-token`).

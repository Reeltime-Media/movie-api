"""
Point the bot's updates at /webhooks/telegram (phone app sign-in via the bot).

Run once per environment, after TELEGRAM_BOT_TOKEN and TELEGRAM_WEBHOOK_SECRET
are set and the API is deployed:
  python scripts/set_telegram_webhook.py --api-url https://api.reeltime.fun

Docker:
  docker compose exec api python scripts/set_telegram_webhook.py --api-url https://api.reeltime.fun

Check the current registration (pending updates, last error):
  python scripts/set_telegram_webhook.py --info

Only one receiver per bot: nothing may call getUpdates on this bot afterwards.
Ops alerts only *send* messages, so they keep working.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--api-url", help="Public API base URL, e.g. https://api.reeltime.fun")
    parser.add_argument("--info", action="store_true", help="Print getWebhookInfo and exit")
    args = parser.parse_args()

    settings = get_settings()
    token = settings.telegram_bot_token.strip()
    if not token:
        print("TELEGRAM_BOT_TOKEN is not set", file=sys.stderr)
        return 1
    bot_api = f"https://api.telegram.org/bot{token}"

    if args.info:
        res = httpx.get(f"{bot_api}/getWebhookInfo", timeout=15)
        print(json.dumps(res.json(), indent=2))
        return 0 if res.is_success else 1

    secret = settings.telegram_webhook_secret.strip()
    api_url = (args.api_url or settings.api_public_url).strip().rstrip("/")
    if not secret:
        print("TELEGRAM_WEBHOOK_SECRET is not set", file=sys.stderr)
        return 1
    if not api_url.startswith("https://"):
        print("--api-url must be the public https:// API base URL", file=sys.stderr)
        return 1

    res = httpx.post(
        f"{bot_api}/setWebhook",
        json={
            "url": f"{api_url}/webhooks/telegram",
            "secret_token": secret,
            "allowed_updates": ["message", "callback_query"],
            "drop_pending_updates": True,
        },
        timeout=15,
    )
    print(json.dumps(res.json(), indent=2))
    return 0 if res.is_success and res.json().get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())

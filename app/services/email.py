"""Transactional email via Resend's REST API."""

import logging

import httpx

from app.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

_CLIENT_TIMEOUT_SECONDS = 15
_RESEND_API_URL = "https://api.resend.com/emails"
_email_client: httpx.AsyncClient | None = None


def _get_email_client() -> httpx.AsyncClient:
    global _email_client
    if _email_client is None:
        _email_client = httpx.AsyncClient(timeout=_CLIENT_TIMEOUT_SECONDS)
    return _email_client


async def close_http_client() -> None:
    global _email_client
    if _email_client is not None:
        await _email_client.aclose()
        _email_client = None


async def send_email(*, to: str, subject: str, html: str, text: str | None = None) -> None:
    """Send via Resend. Logs and swallows failures — a broken email provider
    should never surface as a 500 to the user (or leak account existence)."""
    if not settings.resend_api_key:
        logger.warning("RESEND_API_KEY not configured — skipping email to %s", to)
        return

    payload = {
        "from": settings.resend_from_email,
        "to": [to],
        "subject": subject,
        "html": html,
    }
    if text:
        payload["text"] = text

    client = _get_email_client()
    try:
        res = await client.post(
            _RESEND_API_URL,
            headers={"Authorization": f"Bearer {settings.resend_api_key}"},
            json=payload,
        )
        res.raise_for_status()
    except httpx.HTTPError:
        logger.exception("Failed to send email to %s", to)


# ── Brand shell ───────────────────────────────────────────────────────────
# Email clients strip <style> blocks and don't support flexbox/grid/web
# fonts, so this is a table-based layout with everything inlined — the
# lowest-common-denominator approach that renders consistently in Gmail,
# Outlook, and mobile mail apps.
_BG = "#0A0A0A"
_SURFACE = "#141414"
_BORDER = "#2A2A2A"
_TEXT = "#FAFAFA"
_TEXT_MUTED = "#A3A3A3"
_BRAND = "#E50914"
_FONT_STACK = (
    "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"
)


def _email_shell(*, preheader: str, body_html: str) -> str:
    return f"""\
<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
  </head>
  <body style="margin:0; padding:0; background-color:{_BG};">
    <div style="display:none; max-height:0; overflow:hidden; opacity:0;">{preheader}</div>
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:{_BG};">
      <tr>
        <td align="center" style="padding:40px 16px;">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:480px;">
            <tr>
              <td style="padding-bottom:28px;">
                <table role="presentation" cellpadding="0" cellspacing="0">
                  <tr>
                    <td style="width:26px; height:26px; background-color:{_BRAND}; border-radius:4px; text-align:center; vertical-align:middle; font-family:{_FONT_STACK}; font-size:15px; font-weight:800; color:#ffffff;">
                      R
                    </td>
                    <td style="padding-left:10px; font-family:{_FONT_STACK}; font-size:14px; font-weight:800; letter-spacing:0.06em; color:{_TEXT};">
                      REELTIME
                    </td>
                  </tr>
                </table>
              </td>
            </tr>
            <tr>
              <td style="background-color:{_SURFACE}; border:1px solid {_BORDER}; border-radius:8px; padding:32px;">
                {body_html}
              </td>
            </tr>
            <tr>
              <td style="padding-top:24px; font-family:{_FONT_STACK}; font-size:12px; line-height:1.6; color:{_TEXT_MUTED};">
                Reeltime Media — Cambodia&rsquo;s home for cinema.
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>
"""


def _button(*, href: str, label: str) -> str:
    return f"""\
<table role="presentation" cellpadding="0" cellspacing="0">
  <tr>
    <td style="border-radius:6px; background-color:{_BRAND};">
      <a href="{href}" style="display:inline-block; padding:10px 22px; font-family:{_FONT_STACK}; font-size:13px; font-weight:700; color:#ffffff; text-decoration:none; border-radius:6px;">
        {label}
      </a>
    </td>
  </tr>
</table>
"""


async def send_password_reset_email(*, to: str, reset_link: str) -> None:
    minutes = settings.password_reset_token_expire_minutes
    body = f"""\
<p style="margin:0 0 16px; font-family:{_FONT_STACK}; font-size:17px; font-weight:700; letter-spacing:-0.01em; color:{_TEXT};">
  Reset your password
</p>
<p style="margin:0 0 24px; font-family:{_FONT_STACK}; font-size:13px; line-height:1.6; color:{_TEXT_MUTED};">
  Someone requested a password reset for your Reeltime account. Click below to choose a
  new one. This link expires in {minutes} minutes.
</p>
{_button(href=reset_link, label="Choose a new password")}
<p style="margin:24px 0 0; font-family:{_FONT_STACK}; font-size:12px; line-height:1.6; color:{_TEXT_MUTED};">
  Button not working? Paste this link into your browser:<br />
  <a href="{reset_link}" style="color:{_TEXT_MUTED};">{reset_link}</a>
</p>
<p style="margin:20px 0 0; font-family:{_FONT_STACK}; font-size:12px; line-height:1.6; color:{_TEXT_MUTED};">
  If you didn&rsquo;t request this, you can safely ignore this email.
</p>
"""
    html = _email_shell(preheader="Reset your Reeltime password", body_html=body)
    text = (
        "Someone requested a password reset for your Reeltime account.\n\n"
        f"Reset your password: {reset_link}\n\n"
        f"This link expires in {minutes} minutes.\n\n"
        "If you didn't request this, you can safely ignore this email."
    )
    await send_email(to=to, subject="Reset your Reeltime password", html=html, text=text)

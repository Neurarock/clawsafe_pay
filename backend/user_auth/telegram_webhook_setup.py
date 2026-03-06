"""
Telegram webhook management.

Handles registering / removing the bot webhook with the Telegram API.
When TELEGRAM_WEBHOOK_URL is set the bot uses webhook mode (push);
otherwise it falls back to long-polling (pull) via telegram_poller.

Usage during deployment:
    python -m user_auth.telegram_webhook_setup          # register webhook
    python -m user_auth.telegram_webhook_setup --delete  # remove webhook
"""

from __future__ import annotations

import logging
import secrets

import httpx

from user_auth.config import (
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_WEBHOOK_URL,
    TELEGRAM_WEBHOOK_SECRET,
)

logger = logging.getLogger("user_auth.telegram_webhook_setup")

_TG_BASE = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"


async def register_webhook(url: str | None = None, secret: str | None = None) -> bool:
    """
    Register the Telegram webhook.

    Parameters
    ----------
    url : str, optional
        Override the URL from config.  Defaults to ``TELEGRAM_WEBHOOK_URL``.
    secret : str, optional
        A secret token Telegram will send in the ``X-Telegram-Bot-Api-Secret-Token``
        header so we can verify the request origin.  Defaults to
        ``TELEGRAM_WEBHOOK_SECRET`` (auto-generated if empty).

    Returns True on success.
    """
    webhook_url = url or TELEGRAM_WEBHOOK_URL
    if not webhook_url:
        logger.warning("No TELEGRAM_WEBHOOK_URL configured — skipping webhook registration")
        return False

    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN is not set — cannot register webhook")
        return False

    token = secret or TELEGRAM_WEBHOOK_SECRET or secrets.token_urlsafe(32)

    payload: dict = {
        "url": webhook_url,
        "allowed_updates": ["callback_query"],  # we only care about button presses
        "secret_token": token,
    }

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(f"{_TG_BASE}/setWebhook", json=payload)

    if resp.status_code == 200 and resp.json().get("ok"):
        logger.info(
            "Telegram webhook registered: url=%s (secret_token length=%d)",
            webhook_url,
            len(token),
        )
        return True

    logger.error(
        "Failed to register Telegram webhook: status=%s body=%s",
        resp.status_code,
        resp.text[:300],
    )
    return False


async def delete_webhook() -> bool:
    """Remove the Telegram webhook so the bot can use long-polling."""
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN is not set — cannot delete webhook")
        return False

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(f"{_TG_BASE}/deleteWebhook", json={"drop_pending_updates": False})

    if resp.status_code == 200 and resp.json().get("ok"):
        logger.info("Telegram webhook removed — long-polling mode is now available")
        return True

    logger.error(
        "Failed to delete Telegram webhook: status=%s body=%s",
        resp.status_code,
        resp.text[:300],
    )
    return False


async def get_webhook_info() -> dict:
    """Return the current webhook configuration from Telegram."""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(f"{_TG_BASE}/getWebhookInfo")
    if resp.status_code == 200:
        return resp.json().get("result", {})
    return {}


# ── CLI entry-point ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    import asyncio

    parser = argparse.ArgumentParser(description="Manage Telegram bot webhook")
    parser.add_argument("--delete", action="store_true", help="Remove webhook (switch to polling)")
    parser.add_argument("--info", action="store_true", help="Print current webhook info")
    parser.add_argument("--url", type=str, default=None, help="Override webhook URL")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")

    async def _main():
        if args.info:
            info = await get_webhook_info()
            print(f"Current webhook: {info.get('url', '(none)')}")
            print(f"Pending updates: {info.get('pending_update_count', 0)}")
            print(f"Last error: {info.get('last_error_message', '(none)')}")
        elif args.delete:
            await delete_webhook()
        else:
            await register_webhook(url=args.url)

    asyncio.run(_main())

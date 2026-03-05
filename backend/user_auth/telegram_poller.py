"""
Long-polling poller which fetches Telegram updates and forwards
callback_query updates to the shared handler.

This is intended as a fallback when webhooks are not configured.
"""
import asyncio
import logging
import httpx

from user_auth.config import TELEGRAM_BOT_TOKEN
from user_auth.telegram_handler import process_callback

logger = logging.getLogger("user_auth.telegram_poller")

_POLL_TIMEOUT = 30


async def run_poller(stop_event: asyncio.Event):
    if not TELEGRAM_BOT_TOKEN:
        logger.info("No TELEGRAM_BOT_TOKEN configured; poller disabled")
        return

    offset = None
    base = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

    async with httpx.AsyncClient(timeout=_POLL_TIMEOUT + 10) as client:
        while not stop_event.is_set():
            try:
                params = {"timeout": _POLL_TIMEOUT}
                if offset:
                    params["offset"] = offset

                resp = await client.get(f"{base}/getUpdates", params=params)
                try:
                    resp.raise_for_status()
                except httpx.HTTPStatusError as e:
                    # Telegram returns 409 Conflict when a webhook is set for this bot.
                    status = getattr(e.response, "status_code", None)
                    if status == 409:
                        logger.info(
                            "Telegram returned 409 Conflict — webhook is probably set; stopping poller"
                        )
                        return
                    raise
                data = resp.json()
                if not data.get("ok"):
                    await asyncio.sleep(1)
                    continue

                updates = data.get("result", [])
                for upd in updates:
                    offset = max(offset or 0, upd.get("update_id", 0) + 1)
                    # forward callback_query if present
                    if upd.get("callback_query"):
                        await process_callback(upd.get("callback_query"))

            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Error while polling Telegram updates; sleeping briefly")
                await asyncio.sleep(2)

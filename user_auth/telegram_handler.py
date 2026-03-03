"""
Process Telegram callback_query payloads received either via webhook or polling.
"""
import logging
import httpx

from user_auth import database as db
from user_auth import signer_callback
from user_auth import telegram_bot
from user_auth.config import TELEGRAM_BOT_TOKEN

logger = logging.getLogger("user_auth.telegram_handler")


async def process_callback(callback_query: dict) -> None:
    """Handle a Telegram callback_query dict.

    Expects callback_query to contain keys: id, data, from, message
    """
    if not callback_query:
        return

    data: str = callback_query.get("data", "")
    if ":" not in data:
        return

    action_str, request_id = data.split(":", 1)
    if action_str not in ("approve", "reject"):
        return

    status = "approved" if action_str == "approve" else "rejected"

    req = db.get_request(request_id)
    if not req:
        logger.warning("Telegram callback for unknown request %s", request_id)
        # answer callback to clear loading state
        await _answer_callback(callback_query.get("id"), f"Unknown request {request_id}")
        return

    if req["status"] != "pending":
        logger.info("Telegram callback for already-resolved request %s (status=%s)", request_id, req["status"])
        await _answer_callback(callback_query.get("id"), f"Request already {req['status']}")
        return

    # Update DB
    db.update_status(request_id, status)
    logger.info("Request %s resolved as %s via Telegram", request_id, status)

    # Edit Telegram message to remove buttons
    if req.get("telegram_message_id"):
        await telegram_bot.edit_message_after_resolution(req["telegram_message_id"], status, request_id)

    # Notify signer_service
    await signer_callback.notify_signer_service(request_id, status)
    db.mark_callback_sent(request_id)

    # Answer the callback query so Telegram removes the loading indicator
    await _answer_callback(callback_query.get("id"), f"Request {status}")


async def _answer_callback(callback_query_id: str | None, text: str) -> None:
    if not callback_query_id:
        return
    if not TELEGRAM_BOT_TOKEN:
        logger.warning("No TELEGRAM_BOT_TOKEN configured; cannot answer callback")
        return

    try:
        async with httpx.AsyncClient(timeout=5) as client:
            await client.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/answerCallbackQuery",
                json={"callback_query_id": callback_query_id, "text": text},
            )
    except Exception:
        logger.exception("Failed to answer Telegram callback %s", callback_query_id)

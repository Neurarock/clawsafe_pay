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

    This function answers the callback immediately to clear the Telegram UI
    loading indicator, then performs the heavier work (DB update, editing the
    message, notifying signer_service) in the background.

    Expects callback_query to contain keys: id, data, from, message
    """
    if not callback_query:
        return

    callback_id = callback_query.get("id")
    data: str = callback_query.get("data", "")
    if ":" not in data:
        # answer to clear spinner
        await _answer_callback(callback_id, "Unsupported callback")
        return

    action_str, request_id = data.split(":", 1)
    if action_str not in ("approve", "reject"):
        await _answer_callback(callback_id, "Unsupported action")
        return

    # Answer immediately so the client stops showing the spinner
    await _answer_callback(callback_id, "Processing...")

    # schedule background handling so webhook returns quickly
    try:
        import asyncio

        asyncio.create_task(_handle_callback_in_background(request_id, action_str))
    except Exception:
        logger.exception("Failed to schedule background callback handler for %s", request_id)


async def _handle_callback_in_background(request_id: str, action_str: str) -> None:
    status = "approved" if action_str == "approve" else "rejected"

    req = db.get_request(request_id)
    if not req:
        logger.warning("Background handler: unknown request %s", request_id)
        return

    if req["status"] != "pending":
        logger.info(
            "Background handler: request %s already resolved (status=%s)", request_id, req["status"]
        )
        return

    # Update DB
    db.update_status(request_id, status)
    logger.info("Background handler: Request %s resolved as %s via Telegram", request_id, status)

    # Edit Telegram message to remove buttons
    if req.get("telegram_message_id"):
        try:
            await telegram_bot.edit_message_after_resolution(
                req["telegram_message_id"], status, request_id,
                chat_id_override=req.get("telegram_chat_id", ""),
            )
        except Exception:
            logger.exception("Failed to edit Telegram message for %s", request_id)

    # Notify signer_service
    try:
        await signer_callback.notify_signer_service(request_id, status)
        db.mark_callback_sent(request_id)
    except Exception:
        logger.exception("Failed to notify signer_service for %s", request_id)


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

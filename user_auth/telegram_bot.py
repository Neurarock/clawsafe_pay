"""
Telegram bot integration for sending authentication prompts and
processing user responses via inline keyboard callbacks.
"""

import logging
from typing import Optional

import httpx

from user_auth.config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

logger = logging.getLogger("user_auth.telegram")

BASE_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"


async def send_auth_prompt(request_id: str, user_id: str, action: str) -> Optional[int]:
    """
    Send an inline-keyboard message to the configured Telegram chat
    asking the user to approve or reject the auth request.

    Returns the Telegram message_id on success, or None on failure.
    """
    text = (
        "🔐 *Authentication Request*\n\n"
        f"**Request ID:** `{request_id}`\n"
        f"**User:** `{user_id}`\n"
        f"**Action:** {action}\n\n"
        "Please approve or reject this request:"
    )

    inline_keyboard = {
        "inline_keyboard": [
            [
                {"text": "✅ Approve", "callback_data": f"approve:{request_id}"},
                {"text": "❌ Reject", "callback_data": f"reject:{request_id}"},
            ]
        ]
    }

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
        "reply_markup": inline_keyboard,
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(f"{BASE_URL}/sendMessage", json=payload)
            resp.raise_for_status()
            data = resp.json()
            if data.get("ok"):
                message_id = data["result"]["message_id"]
                logger.info("Telegram message %s sent for request %s", message_id, request_id)
                return message_id
            else:
                logger.error("Telegram API error: %s", data)
                return None
    except Exception:
        logger.exception("Failed to send Telegram message for request %s", request_id)
        return None


async def edit_message_after_resolution(message_id: int, status: str, request_id: str) -> None:
    """
    Edit the original Telegram message to reflect the final status,
    removing the inline keyboard so the buttons can't be tapped again.
    """
    emoji = "✅" if status == "approved" else "❌"
    text = (
        f"{emoji} *Request {status.upper()}*\n\n"
        f"**Request ID:** `{request_id}`\n\n"
        "This request has been resolved."
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "message_id": message_id,
        "text": text,
        "parse_mode": "Markdown",
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(f"{BASE_URL}/editMessageText", json=payload)
            resp.raise_for_status()
    except Exception:
        logger.exception("Failed to edit Telegram message %s", message_id)

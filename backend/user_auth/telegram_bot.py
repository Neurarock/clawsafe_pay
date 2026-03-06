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


def _escape_md2(text: str) -> str:
    """Escape special characters for Telegram MarkdownV2."""
    special = r"_*[]()~`>#+-=|{}.!\\"
    out = []
    for ch in text:
        if ch in special:
            out.append("\\")
        out.append(ch)
    return "".join(out)


async def send_auth_prompt(request_id: str, user_id: str, action: str, chat_id_override: str = "") -> Optional[int]:
    """
    Send an inline-keyboard message to the configured Telegram chat
    asking the user to approve or reject the auth request.

    If chat_id_override is provided, sends to that chat instead of the
    global default TELEGRAM_CHAT_ID.

    Returns the Telegram message_id on success, or None on failure.
    """
    target_chat_id = chat_id_override if chat_id_override else TELEGRAM_CHAT_ID
    if not target_chat_id:
        logger.warning("No Telegram chat ID configured — cannot send auth prompt for %s", request_id)
        return None

    esc = _escape_md2

    # Short request id for display (first 8 chars)
    short_id = request_id[:8] if len(request_id) > 8 else request_id

    text = (
        "🔐  *AUTHORIZATION REQUIRED*\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📋  *Action:*  {esc(action)}\n\n"
        f"👤  *Requested by:*  `{esc(user_id)}`\n"
        f"🆔  *Ref:*  `{esc(short_id)}…`\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "⏳  _This request will expire in 5 minutes\\._\n"
        "⚠️  _Only approve if you initiated this transaction\\._"
    )

    inline_keyboard = {
        "inline_keyboard": [
            [
                {"text": "✅  Approve", "callback_data": f"approve:{request_id}"},
                {"text": "❌  Reject", "callback_data": f"reject:{request_id}"},
            ]
        ]
    }

    payload = {
        "chat_id": target_chat_id,
        "text": text,
        "parse_mode": "MarkdownV2",
        "reply_markup": inline_keyboard,
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(f"{BASE_URL}/sendMessage", json=payload)
            resp.raise_for_status()
            data = resp.json()
            if data.get("ok"):
                message_id = data["result"]["message_id"]
                logger.info("Telegram message %s sent for request %s (chat=%s)", message_id, request_id, target_chat_id)
                return message_id
            else:
                logger.error("Telegram API error: %s", data)
                return None
    except Exception:
        logger.exception("Failed to send Telegram message for request %s", request_id)
        return None


async def edit_message_after_resolution(message_id: int, status: str, request_id: str, chat_id_override: str = "") -> None:
    """
    Edit the original Telegram message to reflect the final status,
    removing the inline keyboard so the buttons can't be tapped again.
    """
    target_chat_id = chat_id_override if chat_id_override else TELEGRAM_CHAT_ID
    esc = _escape_md2
    short_id = request_id[:8] if len(request_id) > 8 else request_id

    if status == "approved":
        emoji = "✅"
        label = "APPROVED"
    elif status == "expired":
        emoji = "⏰"
        label = "EXPIRED"
    else:
        emoji = "❌"
        label = "REJECTED"

    text = (
        f"{emoji}  *{esc(label)}*"
        "\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🆔  *Ref:*  `{esc(short_id)}…`\n\n"
        f"_This request has been {esc(status)}\._"
    )

    payload = {
        "chat_id": target_chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": "MarkdownV2",
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(f"{BASE_URL}/editMessageText", json=payload)
            resp.raise_for_status()
    except Exception:
        logger.exception("Failed to edit Telegram message %s", message_id)

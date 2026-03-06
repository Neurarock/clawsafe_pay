"""
HTTP client that talks to the user_auth service.

1. POST /auth/request — submit an auth request
2. GET  /auth/{request_id} — poll status until resolved
"""

import asyncio
import logging

import httpx

from signer_service.config import USER_AUTH_URL, AUTH_POLL_INTERVAL_SECONDS, AUTH_POLL_TIMEOUT_SECONDS
from signer_service.security import compute_hmac

logger = logging.getLogger("signer_service.auth_client")


async def request_auth(request_id: str, user_id: str, action: str, telegram_chat_id: str = "") -> str:
    """
    Submit an auth request to user_auth and poll until resolved.

    Returns the final status: "approved", "rejected", or "expired".
    Raises TimeoutError if polling exceeds AUTH_POLL_TIMEOUT_SECONDS.
    """
    hmac_digest = compute_hmac(request_id, user_id, action)

    payload = {
        "request_id": request_id,
        "user_id": user_id,
        "action": action,
        "hmac_digest": hmac_digest,
        "telegram_chat_id": telegram_chat_id,
    }

    async with httpx.AsyncClient(timeout=10) as client:
        # Submit auth request
        resp = await client.post(f"{USER_AUTH_URL}/auth/request", json=payload)
        resp.raise_for_status()
        logger.info("Auth request %s submitted to user_auth", request_id)

    # Poll until resolved
    elapsed = 0.0
    while elapsed < AUTH_POLL_TIMEOUT_SECONDS:
        await asyncio.sleep(AUTH_POLL_INTERVAL_SECONDS)
        elapsed += AUTH_POLL_INTERVAL_SECONDS

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{USER_AUTH_URL}/auth/{request_id}")
                resp.raise_for_status()
                data = resp.json()
                status = data.get("status", "pending")
                if status != "pending":
                    logger.info("Auth request %s resolved: %s", request_id, status)
                    return status
        except Exception:
            logger.exception("Error polling auth status for %s", request_id)

    raise TimeoutError(f"Auth request {request_id} not resolved within {AUTH_POLL_TIMEOUT_SECONDS}s")

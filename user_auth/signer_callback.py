"""
Mock signer_service callback client.

In production, signer_service exposes a real endpoint; this module
wraps the HTTP call so we can swap implementations easily.
"""

import logging

import httpx

from user_auth.config import SIGNER_SERVICE_CALLBACK_URL

logger = logging.getLogger("user_auth.signer_callback")


async def notify_signer_service(request_id: str, status: str) -> bool:
    """
    POST the auth result back to signer_service.

    Expected payload:
        {
            "request_id": "<uuid>",
            "status": "approved" | "rejected" | "expired"
        }

    Returns True if the callback was acknowledged (2xx), False otherwise.
    """
    payload = {"request_id": request_id, "status": status}

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(SIGNER_SERVICE_CALLBACK_URL, json=payload)
            resp.raise_for_status()
            logger.info(
                "Signer service callback OK for request %s (status=%s)",
                request_id,
                status,
            )
            return True
    except Exception:
        logger.exception(
            "Signer service callback FAILED for request %s (status=%s)",
            request_id,
            status,
        )
        return False

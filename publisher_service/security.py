"""
Security helpers for publisher_service.
"""
from __future__ import annotations

import hashlib
import hmac

import publisher_service.config as config
from fastapi import Header, HTTPException


def verify_api_key(provided: str) -> bool:
    """Constant-time comparison against PUBLISHER_API_KEY."""
    expected = config.PUBLISHER_API_KEY.encode()
    return hmac.compare_digest(provided.encode(), expected)


async def require_api_key(x_api_key: str = Header(...)):
    if not verify_api_key(x_api_key):
        raise HTTPException(status_code=401, detail="Invalid API key")


def compute_hmac(request_id: str, user_id: str, action: str) -> str:
    """Compute HMAC-SHA256 over canonical fields — mirrors user_auth/security.py."""
    message = f"{request_id}:{user_id}:{action}"
    return hmac.new(
        config.HMAC_SECRET.encode(),
        message.encode(),
        hashlib.sha256,
    ).hexdigest()

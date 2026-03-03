"""
Security helpers for publisher_service.
"""
from __future__ import annotations

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

"""
Async HTTP clients for downstream services:
  - reviewer_service
  - user_auth
  - signer_service
"""
from __future__ import annotations

import logging
from typing import Optional

import httpx

import publisher_service.config as config
from publisher_service.models import ReviewReport, SignerResponse, DraftTx
from publisher_service.security import compute_hmac

logger = logging.getLogger("publisher_service.clients")

_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=5.0)


class DownstreamError(Exception):
    """Raised when a downstream service returns a non-2xx response."""


async def call_reviewer(
    draft_tx: DraftTx,
    current_base_fee_wei: int,
) -> ReviewReport:
    """POST /review to reviewer_service. Returns a ReviewReport."""
    url = f"{config.REVIEWER_SERVICE_URL}/review"
    payload = {
        "intent_id": draft_tx.intent_id,
        "draft_tx": draft_tx.model_dump(mode="json"),
        "current_base_fee_wei": current_base_fee_wei,
    }
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(url, json=payload)
    logger.info("reviewer POST %s → %s", url, resp.status_code)
    if resp.status_code >= 400:
        raise DownstreamError(
            f"reviewer_service returned {resp.status_code}: {resp.text[:200]}"
        )
    return ReviewReport.model_validate(resp.json())


async def request_auth(
    intent_id: str,
    user_id: str,
    action: str,
    auth_request_id: str,
) -> str:
    """POST /auth/request to user_auth. Returns the request_id echoed back."""
    url = f"{config.USER_AUTH_SERVICE_URL}/auth/request"
    digest = compute_hmac(auth_request_id, user_id, action)
    payload = {
        "request_id": auth_request_id,
        "user_id": user_id,
        "action": action,
        "hmac_digest": digest,
    }
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(url, json=payload)
    logger.info("user_auth POST %s → %s", url, resp.status_code)
    if resp.status_code >= 400:
        raise DownstreamError(
            f"user_auth returned {resp.status_code}: {resp.text[:200]}"
        )
    data = resp.json()
    return data.get("request_id", auth_request_id)


async def poll_auth_status(auth_request_id: str) -> str:
    """GET /auth/{auth_request_id} from user_auth. Returns the status string."""
    url = f"{config.USER_AUTH_SERVICE_URL}/auth/{auth_request_id}"
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(url)
    logger.info("user_auth GET %s → %s", url, resp.status_code)
    if resp.status_code >= 400:
        raise DownstreamError(
            f"user_auth returned {resp.status_code}: {resp.text[:200]}"
        )
    return resp.json().get("status", "unknown")


async def call_signer(
    intent_id: str,
    digest: str,
    draft_tx: DraftTx,
    auth_request_id: str,
) -> str:
    """POST /sign to signer_service. Returns tx_hash."""
    url = f"{config.SIGNER_SERVICE_URL}/sign"
    payload = {
        "intent_id": intent_id,
        "digest": digest,
        "draft_tx": draft_tx.model_dump(mode="json"),
        "auth_request_id": auth_request_id,
    }
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(url, json=payload)
    logger.info("signer POST %s → %s", url, resp.status_code)
    if resp.status_code >= 400:
        raise DownstreamError(
            f"signer_service returned {resp.status_code}: {resp.text[:200]}"
        )
    signer_resp = SignerResponse.model_validate(resp.json())
    return signer_resp.tx_hash

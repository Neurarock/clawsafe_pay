"""
Async HTTP clients for downstream services:
  - reviewer_service
  - signer_service

Authentication is handled entirely by signer_service (which talks to
user_auth internally).  Publisher never contacts user_auth directly.
"""
from __future__ import annotations

import logging

import httpx

import publisher_service.config as config
from publisher_service.models import (
    ReviewReport,
    SignerSubmitResponse,
    SignerStatusResponse,
    DraftTx,
)

logger = logging.getLogger("publisher_service.clients")

_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=5.0)


class DownstreamError(Exception):
    """Raised when a downstream service returns a non-2xx response."""


# ── Reviewer ─────────────────────────────────────────────────────────────────


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
        try:
            resp = await client.post(url, json=payload)
        except httpx.HTTPError as exc:
            raise DownstreamError(f"reviewer_service unreachable: {exc}") from exc
    logger.info("reviewer POST %s → %s", url, resp.status_code)
    if resp.status_code >= 400:
        raise DownstreamError(
            f"reviewer_service returned {resp.status_code}: {resp.text[:200]}"
        )
    return ReviewReport.model_validate(resp.json())


# ── Signer ───────────────────────────────────────────────────────────────────


async def submit_to_signer(
    to: str,
    value_wei: str,
    user_id: str,
    note: str = "",
    data: str = "0x",
    gas_limit: int = 21_000,
    chain: str = "sepolia",
    from_address: str = "",
    telegram_chat_id: str = "",
) -> SignerSubmitResponse:
    """
    POST /sign to signer_service.

    The signer handles Telegram auth internally, then signs the tx.
    Returns a SignerSubmitResponse with tx_id for polling.
    """
    url = f"{config.SIGNER_SERVICE_URL}/sign"
    payload = {
        "to": to,
        "value_wei": value_wei,
        "data": data,
        "gas_limit": gas_limit,
        "user_id": user_id,
        "note": note,
        "chain": chain,
        "from_address": from_address,
        "telegram_chat_id": telegram_chat_id,
    }
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(url, json=payload)
    logger.info("signer POST %s → %s", url, resp.status_code)
    if resp.status_code >= 400:
        raise DownstreamError(
            f"signer_service returned {resp.status_code}: {resp.text[:200]}"
        )
    return SignerSubmitResponse.model_validate(resp.json())


async def poll_signer_status(tx_id: str) -> SignerStatusResponse:
    """GET /sign/{tx_id} from signer_service. Returns full status."""
    url = f"{config.SIGNER_SERVICE_URL}/sign/{tx_id}"
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(url)
    logger.info("signer GET %s → %s", url, resp.status_code)
    if resp.status_code >= 400:
        raise DownstreamError(
            f"signer_service returned {resp.status_code}: {resp.text[:200]}"
        )
    return SignerStatusResponse.model_validate(resp.json())

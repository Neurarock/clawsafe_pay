"""
HTTP client tests for publisher_service.
Uses `respx` to mock httpx calls without a real network.
"""
from __future__ import annotations

import json
import pytest
import respx
import httpx

import publisher_service.config as config
from publisher_service.clients import (
    DownstreamError,
    call_reviewer,
    call_signer,
    poll_auth_status,
    request_auth,
)
from publisher_service.security import compute_hmac
from publisher_service.models import ReviewReport
from datetime import datetime, timezone, timedelta
from transaction_builder.models import DraftTx

FAKE_DIGEST = "0x" + "ab" * 32
TO_ADDR = "0xd8da6bf26964af9d7eed9e03e53415d37aa96045"


def _fake_draft(intent_id: str = "client-test-001") -> DraftTx:
    return DraftTx(
        intent_id=intent_id,
        chain_id=11155111,
        from_address="0x742d35cc6634c0532925a3b8d4c9d5a3aa5a3eb",
        to=TO_ADDR,
        value_wei="10000000000000000",
        nonce=1,
        gas_limit=21000,
        max_fee_per_gas="21500000000",
        max_priority_fee_per_gas="1500000000",
        digest=FAKE_DIGEST,
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=120),
    )


# ── call_reviewer ─────────────────────────────────────────────────────────────

@respx.mock
async def test_call_reviewer_success():
    review_payload = {
        "intent_id": "client-test-001",
        "digest": FAKE_DIGEST,
        "verdict": "OK",
        "reasons": [],
        "summary": "Looks fine.",
        "gas_assessment": {"is_reasonable": True, "reference": "normal"},
        "model_used": "test-model",
    }
    route = respx.post(f"{config.REVIEWER_SERVICE_URL}/review").mock(
        return_value=httpx.Response(200, json=review_payload)
    )
    report = await call_reviewer(_fake_draft(), current_base_fee_wei=10_000_000_000)
    assert report.verdict == "OK"
    assert report.digest == FAKE_DIGEST
    payload = json.loads(route.calls[0].request.content.decode())
    assert payload["intent_id"] == "client-test-001"
    assert payload["current_base_fee_wei"] == 10_000_000_000
    assert payload["draft_tx"]["digest"] == FAKE_DIGEST


@respx.mock
async def test_call_reviewer_5xx_raises():
    respx.post(f"{config.REVIEWER_SERVICE_URL}/review").mock(
        return_value=httpx.Response(503, text="Service Unavailable")
    )
    with pytest.raises(DownstreamError):
        await call_reviewer(_fake_draft(), current_base_fee_wei=10_000_000_000)


# ── call_signer ───────────────────────────────────────────────────────────────

@respx.mock
async def test_call_signer_success():
    tx_hash = "0x" + "aa" * 32
    signer_payload = {
        "tx_hash": tx_hash,
        "signed_at": "2026-03-03T12:00:00+00:00",
    }
    route = respx.post(f"{config.SIGNER_SERVICE_URL}/sign").mock(
        return_value=httpx.Response(200, json=signer_payload)
    )
    auth_request_id = "client-test-001:some-uuid"
    result = await call_signer(
        intent_id="client-test-001",
        digest=FAKE_DIGEST,
        draft_tx=_fake_draft(),
        auth_request_id=auth_request_id,
    )
    assert result == tx_hash
    payload = json.loads(route.calls[0].request.content.decode())
    assert payload["intent_id"] == "client-test-001"
    assert payload["digest"] == FAKE_DIGEST
    assert payload["auth_request_id"] == auth_request_id
    assert payload["draft_tx"]["intent_id"] == "client-test-001"


@respx.mock
async def test_call_signer_4xx_raises():
    respx.post(f"{config.SIGNER_SERVICE_URL}/sign").mock(
        return_value=httpx.Response(400, json={"detail": "bad digest"})
    )
    with pytest.raises(DownstreamError):
        await call_signer(
            intent_id="client-test-001",
            digest=FAKE_DIGEST,
            draft_tx=_fake_draft(),
            auth_request_id="client-test-001:some-uuid",
        )


# ── request_auth ──────────────────────────────────────────────────────────────

@respx.mock
async def test_request_auth_success():
    auth_request_id = "req-001"
    route = respx.post(f"{config.USER_AUTH_SERVICE_URL}/auth/request").mock(
        return_value=httpx.Response(200, json={
            "request_id": auth_request_id,
            "status": "pending",
            "message": "sent",
        })
    )
    result = await request_auth(
        intent_id="client-test-001",
        user_id="userA",
        action="approve payment",
        auth_request_id=auth_request_id,
    )
    assert result == auth_request_id
    payload = json.loads(route.calls[0].request.content.decode())
    assert payload["request_id"] == auth_request_id
    assert payload["user_id"] == "userA"
    assert payload["action"] == "approve payment"
    assert payload["hmac_digest"] == compute_hmac(
        request_id=auth_request_id,
        user_id="userA",
        action="approve payment",
    )


@respx.mock
async def test_request_auth_4xx_raises():
    respx.post(f"{config.USER_AUTH_SERVICE_URL}/auth/request").mock(
        return_value=httpx.Response(401, json={"detail": "invalid hmac"})
    )
    with pytest.raises(DownstreamError):
        await request_auth(
            intent_id="client-test-001",
            user_id="userA",
            action="approve payment",
            auth_request_id="req-002",
        )


# ── poll_auth_status ──────────────────────────────────────────────────────────

@respx.mock
async def test_poll_auth_status_returns_status():
    auth_request_id = "req-001"
    respx.get(f"{config.USER_AUTH_SERVICE_URL}/auth/{auth_request_id}").mock(
        return_value=httpx.Response(200, json={
            "request_id": auth_request_id,
            "status": "approved",
            "user_id": "userA",
            "action": "pay",
            "created_at": "2026-03-03T12:00:00+00:00",
            "resolved_at": "2026-03-03T12:00:05+00:00",
        })
    )
    status = await poll_auth_status(auth_request_id)
    assert status == "approved"


@respx.mock
async def test_poll_auth_status_5xx_raises():
    auth_request_id = "req-err"
    respx.get(f"{config.USER_AUTH_SERVICE_URL}/auth/{auth_request_id}").mock(
        return_value=httpx.Response(503, text="unavailable")
    )
    with pytest.raises(DownstreamError):
        await poll_auth_status(auth_request_id)

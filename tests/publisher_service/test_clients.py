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
    submit_to_signer,
    poll_signer_status,
)
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


# ── submit_to_signer ─────────────────────────────────────────────────────────

@respx.mock
async def test_submit_to_signer_success():
    signer_payload = {
        "tx_id": "signer-tx-001",
        "status": "pending_auth",
        "message": "Transaction queued — waiting for Telegram approval",
    }
    route = respx.post(f"{config.SIGNER_SERVICE_URL}/sign").mock(
        return_value=httpx.Response(202, json=signer_payload)
    )
    result = await submit_to_signer(
        to=TO_ADDR,
        value_wei="10000000000000000",
        user_id="userA",
        note="test payment",
        data="0x",
        gas_limit=21000,
    )
    assert result.tx_id == "signer-tx-001"
    assert result.status == "pending_auth"
    payload = json.loads(route.calls[0].request.content.decode())
    assert payload["to"] == TO_ADDR
    assert payload["value_wei"] == "10000000000000000"
    assert payload["user_id"] == "userA"
    assert payload["note"] == "test payment"


@respx.mock
async def test_submit_to_signer_4xx_raises():
    respx.post(f"{config.SIGNER_SERVICE_URL}/sign").mock(
        return_value=httpx.Response(400, json={"detail": "Invalid recipient address"})
    )
    with pytest.raises(DownstreamError):
        await submit_to_signer(
            to="bad-address",
            value_wei="10000000000000000",
            user_id="userA",
        )


# ── poll_signer_status ────────────────────────────────────────────────────────

@respx.mock
async def test_poll_signer_status_signed():
    tx_id = "signer-tx-001"
    tx_hash = "0x" + "aa" * 32
    respx.get(f"{config.SIGNER_SERVICE_URL}/sign/{tx_id}").mock(
        return_value=httpx.Response(200, json={
            "tx_id": tx_id,
            "status": "signed",
            "to": TO_ADDR,
            "value_wei": "10000000000000000",
            "user_id": "userA",
            "note": "test",
            "signed_tx_hash": tx_hash,
            "created_at": "2026-03-03T12:00:00+00:00",
            "resolved_at": "2026-03-03T12:00:10+00:00",
        })
    )
    result = await poll_signer_status(tx_id)
    assert result.status == "signed"
    assert result.signed_tx_hash == tx_hash


@respx.mock
async def test_poll_signer_status_pending():
    tx_id = "signer-tx-002"
    respx.get(f"{config.SIGNER_SERVICE_URL}/sign/{tx_id}").mock(
        return_value=httpx.Response(200, json={
            "tx_id": tx_id,
            "status": "pending_auth",
            "to": TO_ADDR,
            "value_wei": "10000000000000000",
            "user_id": "userA",
            "note": "test",
            "created_at": "2026-03-03T12:00:00+00:00",
        })
    )
    result = await poll_signer_status(tx_id)
    assert result.status == "pending_auth"


@respx.mock
async def test_poll_signer_status_404_raises():
    tx_id = "does-not-exist"
    respx.get(f"{config.SIGNER_SERVICE_URL}/sign/{tx_id}").mock(
        return_value=httpx.Response(404, json={"detail": "Transaction not found"})
    )
    with pytest.raises(DownstreamError):
        await poll_signer_status(tx_id)


@respx.mock
async def test_poll_signer_status_5xx_raises():
    tx_id = "signer-tx-err"
    respx.get(f"{config.SIGNER_SERVICE_URL}/sign/{tx_id}").mock(
        return_value=httpx.Response(503, text="unavailable")
    )
    with pytest.raises(DownstreamError):
        await poll_signer_status(tx_id)

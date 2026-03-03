"""
Orchestrator workflow tests — all downstream calls are mocked.
"""
from __future__ import annotations

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, patch
from datetime import datetime, timezone, timedelta

import publisher_service.database as db
from publisher_service.clients import DownstreamError
from publisher_service.orchestrator import run_intent_workflow
from publisher_service.models import ReviewReport
from transaction_builder.models import DraftTx, PolicyError, ProviderError

# ── Helpers ──────────────────────────────────────────────────────────────────

INTENT_ID = "orch-test-001"
FROM_ADDR = "0x742d35cc6634c0532925a3b8d4c9d5a3aa5a3eb"
TO_ADDR = "0xd8da6bf26964af9d7eed9e03e53415d37aa96045"
FAKE_DIGEST = "0x" + "ab" * 32
FAKE_TX_HASH = "0x" + "aa" * 32


def _fake_draft() -> DraftTx:
    return DraftTx(
        intent_id=INTENT_ID,
        chain_id=11155111,
        from_address=FROM_ADDR,
        to=TO_ADDR,
        value_wei="10000000000000000",
        nonce=5,
        gas_limit=21000,
        max_fee_per_gas="21500000000",
        max_priority_fee_per_gas="1500000000",
        digest=FAKE_DIGEST,
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=120),
    )


def _ok_review(verdict: str = "OK") -> ReviewReport:
    return ReviewReport(
        intent_id=INTENT_ID,
        digest=FAKE_DIGEST,
        verdict=verdict,
        reasons=[],
        summary="Looks fine.",
        gas_assessment={"is_reasonable": True, "reference": "normal"},
        model_used="test-model",
    )


def _insert_test_intent(intent_id: str = INTENT_ID):
    db.init_db()
    db.insert_intent(
        intent_id=intent_id,
        from_user="userA",
        to_user="userB",
        to_address=TO_ADDR,
        amount_wei="10000000000000000",
        note="test",
    )


# ── Tests ─────────────────────────────────────────────────────────────────────

@patch("publisher_service.orchestrator.call_signer", new_callable=AsyncMock)
@patch("publisher_service.orchestrator.poll_auth_status", new_callable=AsyncMock)
@patch("publisher_service.orchestrator.request_auth", new_callable=AsyncMock)
@patch("publisher_service.orchestrator.call_reviewer", new_callable=AsyncMock)
@patch("publisher_service.orchestrator.build_draft_tx", new_callable=AsyncMock)
async def test_happy_path_reaches_confirmed(
    mock_build, mock_review, mock_request_auth, mock_poll, mock_sign
):
    _insert_test_intent()
    mock_build.return_value = _fake_draft()
    mock_review.return_value = _ok_review("OK")
    mock_request_auth.return_value = f"{INTENT_ID}:some-uuid"
    mock_poll.return_value = "approved"
    mock_sign.return_value = FAKE_TX_HASH

    await run_intent_workflow(INTENT_ID)

    row = db.get_intent(INTENT_ID)
    assert row["status"] == "confirmed"
    assert row["tx_hash"] == FAKE_TX_HASH
    mock_sign.assert_called_once()


@patch("publisher_service.orchestrator.call_signer", new_callable=AsyncMock)
@patch("publisher_service.orchestrator.poll_auth_status", new_callable=AsyncMock)
@patch("publisher_service.orchestrator.request_auth", new_callable=AsyncMock)
@patch("publisher_service.orchestrator.call_reviewer", new_callable=AsyncMock)
@patch("publisher_service.orchestrator.build_draft_tx", new_callable=AsyncMock)
async def test_reviewer_block_stops_workflow(
    mock_build, mock_review, mock_request_auth, mock_poll, mock_sign
):
    _insert_test_intent()
    mock_build.return_value = _fake_draft()
    mock_review.return_value = ReviewReport(
        intent_id=INTENT_ID,
        digest=FAKE_DIGEST,
        verdict="BLOCK",
        reasons=["suspicious amount"],
        summary="Blocked.",
        gas_assessment={},
        model_used="test",
    )

    await run_intent_workflow(INTENT_ID)

    row = db.get_intent(INTENT_ID)
    assert row["status"] == "blocked"
    mock_sign.assert_not_called()
    mock_request_auth.assert_not_called()


@patch("publisher_service.orchestrator.call_signer", new_callable=AsyncMock)
@patch("publisher_service.orchestrator.poll_auth_status", new_callable=AsyncMock)
@patch("publisher_service.orchestrator.request_auth", new_callable=AsyncMock)
@patch("publisher_service.orchestrator.call_reviewer", new_callable=AsyncMock)
@patch("publisher_service.orchestrator.build_draft_tx", new_callable=AsyncMock)
async def test_user_rejection_sets_rejected(
    mock_build, mock_review, mock_request_auth, mock_poll, mock_sign
):
    _insert_test_intent()
    mock_build.return_value = _fake_draft()
    mock_review.return_value = _ok_review()
    mock_request_auth.return_value = f"{INTENT_ID}:uuid"
    mock_poll.return_value = "rejected"

    await run_intent_workflow(INTENT_ID)

    assert db.get_intent(INTENT_ID)["status"] == "rejected"
    mock_sign.assert_not_called()


@patch("publisher_service.orchestrator.call_signer", new_callable=AsyncMock)
@patch("publisher_service.orchestrator.poll_auth_status", new_callable=AsyncMock)
@patch("publisher_service.orchestrator.request_auth", new_callable=AsyncMock)
@patch("publisher_service.orchestrator.call_reviewer", new_callable=AsyncMock)
@patch("publisher_service.orchestrator.build_draft_tx", new_callable=AsyncMock)
async def test_approval_timeout_sets_expired(
    mock_build, mock_review, mock_request_auth, mock_poll, mock_sign
):
    """Poll always returns 'pending'; timeout fires → expired."""
    _insert_test_intent()
    mock_build.return_value = _fake_draft()
    mock_review.return_value = _ok_review()
    mock_request_auth.return_value = f"{INTENT_ID}:uuid"
    mock_poll.return_value = "pending"   # never becomes approved

    await run_intent_workflow(INTENT_ID)

    assert db.get_intent(INTENT_ID)["status"] == "expired"
    mock_sign.assert_not_called()


@patch("publisher_service.orchestrator.build_draft_tx", new_callable=AsyncMock)
async def test_policy_error_sets_failed(mock_build):
    _insert_test_intent()
    mock_build.side_effect = PolicyError("amount exceeds cap")

    await run_intent_workflow(INTENT_ID)

    row = db.get_intent(INTENT_ID)
    assert row["status"] == "failed"
    assert "Policy violation" in row["error_message"]


@patch("publisher_service.orchestrator.build_draft_tx", new_callable=AsyncMock)
async def test_provider_error_sets_failed(mock_build):
    _insert_test_intent()
    mock_build.side_effect = ProviderError("rpc unavailable")

    await run_intent_workflow(INTENT_ID)

    row = db.get_intent(INTENT_ID)
    assert row["status"] == "failed"
    assert "Provider error" in row["error_message"]


@patch("publisher_service.orchestrator.build_draft_tx", new_callable=AsyncMock)
async def test_unexpected_build_error_sets_failed(mock_build):
    _insert_test_intent()
    mock_build.side_effect = RuntimeError("boom")

    await run_intent_workflow(INTENT_ID)

    row = db.get_intent(INTENT_ID)
    assert row["status"] == "failed"
    assert "Build error" in row["error_message"]


@patch("publisher_service.orchestrator.call_signer", new_callable=AsyncMock)
@patch("publisher_service.orchestrator.poll_auth_status", new_callable=AsyncMock)
@patch("publisher_service.orchestrator.request_auth", new_callable=AsyncMock)
@patch("publisher_service.orchestrator.call_reviewer", new_callable=AsyncMock)
@patch("publisher_service.orchestrator.build_draft_tx", new_callable=AsyncMock)
async def test_digest_mismatch_sets_failed(
    mock_build, mock_review, mock_request_auth, mock_poll, mock_sign
):
    """Review report returns a different digest → security alert → failed."""
    _insert_test_intent()
    mock_build.return_value = _fake_draft()
    # Tampered digest in review report
    tampered_digest = "0x" + "ff" * 32
    mock_review.return_value = ReviewReport(
        intent_id=INTENT_ID,
        digest=tampered_digest,
        verdict="OK",
        reasons=[],
        summary="Fine.",
        gas_assessment={},
        model_used="test",
    )

    await run_intent_workflow(INTENT_ID)

    row = db.get_intent(INTENT_ID)
    assert row["status"] == "failed"
    assert "SECURITY" in row["error_message"] or "digest" in row["error_message"]
    mock_sign.assert_not_called()


@patch("publisher_service.orchestrator.call_signer", new_callable=AsyncMock)
@patch("publisher_service.orchestrator.poll_auth_status", new_callable=AsyncMock)
@patch("publisher_service.orchestrator.request_auth", new_callable=AsyncMock)
@patch("publisher_service.orchestrator.call_reviewer", new_callable=AsyncMock)
@patch("publisher_service.orchestrator.build_draft_tx", new_callable=AsyncMock)
async def test_reviewer_downstream_error_defaults_to_warn_and_continues(
    mock_build, mock_review, mock_request_auth, mock_poll, mock_sign
):
    _insert_test_intent()
    mock_build.return_value = _fake_draft()
    mock_review.side_effect = DownstreamError("reviewer down")
    mock_request_auth.return_value = f"{INTENT_ID}:uuid"
    mock_poll.return_value = "approved"
    mock_sign.return_value = FAKE_TX_HASH

    await run_intent_workflow(INTENT_ID)

    row = db.get_intent(INTENT_ID)
    assert row["status"] == "confirmed"
    report = json.loads(row["review_report_json"])
    assert report["verdict"] == "WARN"
    assert "unreachable" in report["reasons"][0]
    mock_sign.assert_called_once()


@patch("publisher_service.orchestrator.call_signer", new_callable=AsyncMock)
@patch("publisher_service.orchestrator.poll_auth_status", new_callable=AsyncMock)
@patch("publisher_service.orchestrator.request_auth", new_callable=AsyncMock)
@patch("publisher_service.orchestrator.call_reviewer", new_callable=AsyncMock)
@patch("publisher_service.orchestrator.build_draft_tx", new_callable=AsyncMock)
async def test_auth_request_error_sets_failed(
    mock_build, mock_review, mock_request_auth, mock_poll, mock_sign
):
    _insert_test_intent()
    mock_build.return_value = _fake_draft()
    mock_review.return_value = _ok_review()
    mock_request_auth.side_effect = DownstreamError("auth down")

    await run_intent_workflow(INTENT_ID)

    row = db.get_intent(INTENT_ID)
    assert row["status"] == "failed"
    assert "Auth request error" in row["error_message"]
    mock_poll.assert_not_called()
    mock_sign.assert_not_called()


@patch("publisher_service.orchestrator.call_signer", new_callable=AsyncMock)
@patch("publisher_service.orchestrator.poll_auth_status", new_callable=AsyncMock)
@patch("publisher_service.orchestrator.request_auth", new_callable=AsyncMock)
@patch("publisher_service.orchestrator.call_reviewer", new_callable=AsyncMock)
@patch("publisher_service.orchestrator.build_draft_tx", new_callable=AsyncMock)
async def test_poll_auth_transient_error_eventually_approved(
    mock_build, mock_review, mock_request_auth, mock_poll, mock_sign
):
    _insert_test_intent()
    mock_build.return_value = _fake_draft()
    mock_review.return_value = _ok_review()
    mock_request_auth.return_value = f"{INTENT_ID}:uuid"
    mock_poll.side_effect = [DownstreamError("temporary"), "approved"]
    mock_sign.return_value = FAKE_TX_HASH

    await run_intent_workflow(INTENT_ID)

    row = db.get_intent(INTENT_ID)
    assert row["status"] == "confirmed"
    mock_sign.assert_called_once()


@patch("publisher_service.orchestrator.call_signer", new_callable=AsyncMock)
@patch("publisher_service.orchestrator.poll_auth_status", new_callable=AsyncMock)
@patch("publisher_service.orchestrator.request_auth", new_callable=AsyncMock)
@patch("publisher_service.orchestrator.call_reviewer", new_callable=AsyncMock)
@patch("publisher_service.orchestrator.build_draft_tx", new_callable=AsyncMock)
async def test_signer_error_sets_failed(
    mock_build, mock_review, mock_request_auth, mock_poll, mock_sign
):
    _insert_test_intent()
    mock_build.return_value = _fake_draft()
    mock_review.return_value = _ok_review()
    mock_request_auth.return_value = f"{INTENT_ID}:uuid"
    mock_poll.return_value = "approved"
    mock_sign.side_effect = DownstreamError("signer rejected")

    await run_intent_workflow(INTENT_ID)

    row = db.get_intent(INTENT_ID)
    assert row["status"] == "failed"
    assert "Signer error" in row["error_message"]


@patch("publisher_service.orchestrator.call_signer", new_callable=AsyncMock)
@patch("publisher_service.orchestrator.poll_auth_status", new_callable=AsyncMock)
@patch("publisher_service.orchestrator.request_auth", new_callable=AsyncMock)
@patch("publisher_service.orchestrator.call_reviewer", new_callable=AsyncMock)
@patch("publisher_service.orchestrator.build_draft_tx", new_callable=AsyncMock)
async def test_reviewer_warn_does_not_block(
    mock_build, mock_review, mock_request_auth, mock_poll, mock_sign
):
    """WARN verdict should NOT block — workflow continues to approval."""
    _insert_test_intent()
    mock_build.return_value = _fake_draft()
    mock_review.return_value = _ok_review("WARN")  # WARN, not BLOCK
    mock_request_auth.return_value = f"{INTENT_ID}:uuid"
    mock_poll.return_value = "approved"
    mock_sign.return_value = FAKE_TX_HASH

    await run_intent_workflow(INTENT_ID)

    assert db.get_intent(INTENT_ID)["status"] == "confirmed"
    mock_sign.assert_called_once()


# ── State machine invariants ──────────────────────────────────────────────────

TERMINAL = {"confirmed", "rejected", "expired", "blocked", "failed"}
ALL_STATUSES = {
    "pending", "building", "reviewing", "awaiting_approval",
    "signing", "broadcast", "confirmed",
    "rejected", "expired", "blocked", "failed",
}


@patch("publisher_service.orchestrator.build_draft_tx", new_callable=AsyncMock)
async def test_terminal_state_not_overwritten(mock_build):
    """Once an intent is in a terminal state, update_status must not change it."""
    db.init_db()
    db.insert_intent("inv-001", "u1", "u2", TO_ADDR, "1000", "")
    db.update_status("inv-001", "failed", error="test error")
    # Attempt to move to another status
    db.update_status("inv-001", "confirmed")
    assert db.get_intent("inv-001")["status"] == "failed"


async def test_all_valid_statuses_are_recognised():
    db.init_db()
    db.insert_intent("inv-002", "u1", "u2", TO_ADDR, "1000", "")
    row = db.get_intent("inv-002")
    assert row["status"] in ALL_STATUSES

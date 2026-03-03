"""
Core orchestration workflow for publisher_service.

run_intent_workflow(intent_id) drives an intent through the full state machine:
  pending → building → reviewing → awaiting_approval → signing → broadcast → confirmed
                                                                ↘
                                             rejected / expired / blocked / failed
"""
from __future__ import annotations

import asyncio
import logging
import time
from uuid import uuid4

import publisher_service.config as config
import publisher_service.database as db
from publisher_service.clients import (
    DownstreamError,
    call_reviewer,
    call_signer,
    poll_auth_status,
    request_auth,
)
from transaction_builder import (
    PolicyConfig,
    PolicyError,
    ProviderError,
    Web3Provider,
    build_draft_tx,
)
from transaction_builder.models import PaymentIntent

logger = logging.getLogger("publisher_service.orchestrator")


def _make_policy() -> PolicyConfig:
    return PolicyConfig(
        recipient_allowlist=config.POLICY_RECIPIENT_ALLOWLIST,
        max_amount_wei=config.POLICY_MAX_AMOUNT_WEI,
        tip_wei=config.POLICY_TIP_WEI,
    )


async def run_intent_workflow(intent_id: str) -> None:
    """Drive intent through the full state machine. Errors are caught and recorded."""
    row = db.get_intent(intent_id)
    if not row:
        logger.error("Intent %s not found — aborting workflow", intent_id)
        return

    intent = PaymentIntent(
        intent_id=row["intent_id"],
        from_user=row["from_user"],
        to_user=row["to_user"],
        amount_wei=row["amount_wei"],
        to_address=row["to_address"],
        note=row["note"],
    )

    # ── Step 1: Build DraftTx ────────────────────────────────────────────────
    db.update_status(intent_id, "building")
    policy = _make_policy()
    provider = Web3Provider(config.SEPOLIA_RPC_URL)

    try:
        draft = await build_draft_tx(intent, provider, config.SIGNER_FROM_ADDRESS, policy)
    except PolicyError as exc:
        db.update_status(intent_id, "failed", error=f"Policy violation: {exc.reason}")
        return
    except ProviderError as exc:
        db.update_status(intent_id, "failed", error=f"Provider error: {exc}")
        return
    except Exception as exc:
        db.update_status(intent_id, "failed", error=f"Build error: {exc}")
        return

    db.store_draft_tx(intent_id, draft)
    db.update_status(intent_id, "reviewing")

    # ── Step 2: Call Reviewer ────────────────────────────────────────────────
    try:
        # Pass the current base fee from the draft's max fee estimate (best proxy without re-fetching)
        current_base_fee_wei = int(draft.max_fee_per_gas) - int(draft.max_priority_fee_per_gas)
        review = await call_reviewer(draft, max(current_base_fee_wei, 0))
    except DownstreamError as exc:
        # Reviewer unreachable — default to WARN as per spec
        logger.warning(
            "Intent %s: reviewer_service unreachable (%s) — defaulting to WARN", intent_id, exc
        )
        from publisher_service.models import ReviewReport
        review = ReviewReport(
            intent_id=intent_id,
            digest=draft.digest,
            verdict="WARN",
            reasons=["reviewer_service unreachable — defaulted to WARN"],
            summary="Reviewer unavailable; proceeding with caution.",
            gas_assessment={"is_reasonable": True, "reference": "unavailable"},
            model_used="none",
        )
    except Exception as exc:
        db.update_status(intent_id, "failed", error=f"Reviewer error: {exc}")
        return

    db.store_review_report(intent_id, review.model_dump())

    # ── Security invariant: digest consistency check ─────────────────────────
    if review.digest != draft.digest:
        logger.error(
            "SECURITY ALERT: intent %s — digest mismatch! draft=%s review=%s",
            intent_id, draft.digest, review.digest,
        )
        db.update_status(
            intent_id, "failed",
            error=f"SECURITY: digest mismatch draft={draft.digest[:10]} review={review.digest[:10]}",
        )
        return

    if review.verdict == "BLOCK":
        logger.info("Intent %s: reviewer returned BLOCK — %s", intent_id, review.reasons)
        db.update_status(intent_id, "blocked")
        return

    logger.info("Intent %s: reviewer verdict=%s, continuing", intent_id, review.verdict)

    # ── Step 3: Request Telegram Approval ────────────────────────────────────
    auth_request_id = f"{intent_id}:{uuid4()}"
    action = (
        f"Pay {intent.amount_wei} wei ({int(intent.amount_wei)/1e18:.6f} ETH) "
        f"to {draft.to} on Sepolia | "
        f"Gas: {draft.gas_limit} × {int(draft.max_fee_per_gas)//1_000_000_000} gwei | "
        f"Reviewer: {review.verdict} | "
        f"Digest: {draft.digest[:10]}…{draft.digest[-6:]}"
    )

    try:
        await request_auth(
            intent_id=intent_id,
            user_id=intent.from_user,
            action=action,
            auth_request_id=auth_request_id,
        )
    except DownstreamError as exc:
        db.update_status(intent_id, "failed", error=f"Auth request error: {exc}")
        return

    db.store_auth_request_id(intent_id, auth_request_id)
    db.update_status(intent_id, "awaiting_approval")

    # ── Step 4: Poll for Approval ────────────────────────────────────────────
    deadline = time.monotonic() + config.APPROVAL_TIMEOUT_SECONDS
    approval_status = "pending"

    while time.monotonic() < deadline:
        await asyncio.sleep(config.APPROVAL_POLL_INTERVAL_SECONDS)
        try:
            approval_status = await poll_auth_status(auth_request_id)
        except DownstreamError as exc:
            logger.warning("Intent %s: poll_auth error — %s", intent_id, exc)
            continue

        if approval_status == "approved":
            break
        if approval_status in ("rejected", "expired"):
            db.update_status(intent_id, approval_status)
            return
        # "pending" → keep polling
    else:
        # Loop exhausted without approval
        db.update_status(intent_id, "expired")
        return

    if approval_status != "approved":
        db.update_status(intent_id, "expired")
        return

    # ── Step 5: Call Signer ──────────────────────────────────────────────────
    db.update_status(intent_id, "signing")
    try:
        tx_hash = await call_signer(
            intent_id=intent_id,
            digest=draft.digest,
            draft_tx=draft,
            auth_request_id=auth_request_id,
        )
    except DownstreamError as exc:
        db.update_status(intent_id, "failed", error=f"Signer error: {exc}")
        return

    db.store_tx_hash(intent_id, tx_hash)
    db.update_status(intent_id, "broadcast")
    # MVP: treat broadcast as confirmed immediately
    db.update_status(intent_id, "confirmed")
    logger.info("Intent %s confirmed. tx_hash=%s", intent_id, tx_hash)

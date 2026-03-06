"""
Core orchestration workflow for publisher_service.

run_intent_workflow(intent_id) drives an intent through the full state machine:
  pending → building → reviewing → signing → broadcast → confirmed
                                                        ↘
                             rejected / expired / blocked / failed

Authentication is handled entirely by signer_service.  The publisher
submits signing requests and polls for results — it never contacts
user_auth directly.
"""
from __future__ import annotations

import asyncio
import logging
import time

import publisher_service.config as config
import publisher_service.database as db
import publisher_service.api_users_db as api_users_db
from publisher_service.clients import (
    DownstreamError,
    call_reviewer,
    submit_to_signer,
    poll_signer_status,
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

# Signer statuses that mean "still in progress"
_SIGNER_PENDING_STATUSES = {"pending_auth", "approved"}  # "broadcast" is terminal success


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
        from_address=row.get("from_address", ""),
        note=row["note"],
        chain=row.get("chain", "sepolia"),
        asset=row.get("asset", "ETH"),
    )

    # ── Resolve chain config ─────────────────────────────────────────────────
    from chains import get_chain
    try:
        chain_reg = get_chain(intent.chain)
        chain_cfg = chain_reg.config
        rpc_url = chain_cfg.default_rpc_url or config.SEPOLIA_RPC_URL
        chain_display = chain_cfg.display_name
    except KeyError:
        logger.warning("Chain %r not in registry, falling back to Sepolia", intent.chain)
        rpc_url = config.SEPOLIA_RPC_URL
        chain_display = "Sepolia Testnet"

    # ── Step 1: Build DraftTx ────────────────────────────────────────────────
    db.update_status(intent_id, "building")
    policy = _make_policy()
    provider = Web3Provider(rpc_url)

    # Use the wallet address from the intent, or fall back to the default
    from_address = intent.from_address or config.SIGNER_FROM_ADDRESS

    try:
        draft = await build_draft_tx(intent, provider, from_address, policy)
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

    # ── Step 3: Submit to Signer ─────────────────────────────────────────────
    #   The signer_service handles Telegram auth internally.
    #   We just submit the tx details and poll for the result.
    db.update_status(intent_id, "signing")

    reviewer_line = f'Reviewer recommends "{review.verdict}"'
    if review.reasons:
        reviewer_line += ": " + "; ".join(review.reasons[:2])  # cap at 2 for readability
    elif review.summary:
        reviewer_line += f": {review.summary}"

    note = (
        f"Pay {int(intent.amount_wei)/1e18:.6f} {intent.asset} "
        f"to {draft.to} on {chain_display} | "
        f"{reviewer_line} | "
        f"Digest: {draft.digest[:10]}…{draft.digest[-6:]}"
    )

    try:
        # Resolve the telegram_chat_id from the agent who submitted this intent
        agent_chat_id = ""
        api_user_id = row.get("api_user_id", "")
        if api_user_id:
            agent = api_users_db.get_api_user(api_user_id)
            if agent:
                agent_chat_id = agent.get("telegram_chat_id", "")

        signer_resp = await submit_to_signer(
            to=draft.to,
            value_wei=draft.value_wei,
            user_id=intent.from_user,
            note=note,
            data=draft.data,
            gas_limit=draft.gas_limit,
            chain=intent.chain,
            from_address=from_address,
            telegram_chat_id=agent_chat_id,
        )
    except DownstreamError as exc:
        db.update_status(intent_id, "failed", error=f"Signer submit error: {exc}")
        return

    signer_tx_id = signer_resp.tx_id
    db.store_signer_tx_id(intent_id, signer_tx_id)
    logger.info("Intent %s: submitted to signer, tx_id=%s", intent_id, signer_tx_id)

    # ── Step 4: Poll Signer for Result ───────────────────────────────────────
    deadline = time.monotonic() + config.SIGNER_POLL_TIMEOUT_SECONDS

    try:
        while time.monotonic() < deadline:
            await asyncio.sleep(config.SIGNER_POLL_INTERVAL_SECONDS)
            try:
                status_resp = await poll_signer_status(signer_tx_id)
            except Exception as exc:
                logger.warning("Intent %s: signer poll error — %s", intent_id, exc)
                continue

            signer_status = status_resp.status

            if signer_status in _SIGNER_PENDING_STATUSES:
                continue  # still in progress

            # Terminal states
            if signer_status in ("signed", "broadcast"):
                if status_resp.signed_tx_hash:
                    db.store_tx_hash(intent_id, status_resp.signed_tx_hash)
                db.update_status(intent_id, "broadcast")
                db.update_status(intent_id, "confirmed")
                logger.info(
                    "Intent %s confirmed. tx_hash=%s", intent_id, status_resp.signed_tx_hash,
                )
                return

            if signer_status == "rejected":
                db.update_status(intent_id, "rejected")
                logger.info("Intent %s rejected by user", intent_id)
                return

            if signer_status == "expired":
                db.update_status(intent_id, "expired")
                return

            if signer_status == "sign_failed":
                reason = status_resp.error_reason or "unknown error"
                db.update_status(
                    intent_id, "failed",
                    error=f"Signing/broadcast failed: {reason}",
                )
                logger.error("Intent %s SIGN_FAILED: %s", intent_id, reason)
                return

            # Unknown status — keep polling
            logger.warning(
                "Intent %s: unknown signer status %r — continuing poll",
                intent_id, signer_status,
            )
        else:
            # Timeout
            db.update_status(intent_id, "expired", error="Signer poll timeout")
            logger.warning("Intent %s: signer poll timed out", intent_id)
    except Exception as exc:
        logger.error("Intent %s: poll loop crashed — %s", intent_id, exc, exc_info=True)
        db.update_status(intent_id, "failed", error=f"Poll error: {exc}")

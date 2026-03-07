"""
Signer Service – FastAPI application.

Endpoints
---------
POST /sign              Submit a transaction for signing (requires Telegram auth)
GET  /sign/{tx_id}      Check the status of a signing request
POST /auth/callback     Receive auth results from user_auth (callback mode)
GET  /health            Health-check
"""

import asyncio
import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from signer_service import database as db
from signer_service.models import (
    SignRequest,
    SignResponse,
    TxStatusResponse,
    AuthCallbackPayload,
)
from signer_service.auth_client import request_auth
from signer_service.signer import sign_transaction
from signer_service.config import WALLET_ADDRESS, get_wallet_addresses

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s  %(message)s",
)
logger = logging.getLogger("signer_service.app")

# Track background signing tasks so we can cancel on shutdown
_background_tasks: set[asyncio.Task] = set()


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    logger.info("Signer DB initialised")
    yield
    # Cancel pending background tasks
    for t in _background_tasks:
        t.cancel()
    await asyncio.gather(*_background_tasks, return_exceptions=True)


app = FastAPI(
    title="ClawSafe Pay – Signer Service",
    version="0.1.0",
    lifespan=lifespan,
)


# ── Rate-limit middleware ───────────────────────────────────────────────────
_rate_limit_store: dict[str, list[float]] = {}
_RATE_LIMIT_MAX = 600
_RATE_LIMIT_WINDOW = 60.0
_RATE_LIMIT_EXEMPT = frozenset({
    "/health",
    "/docs",
    "/openapi.json",
})
_RATE_LIMIT_EXEMPT_PREFIXES = (
    "/auth/",   # inter-service callbacks from user_auth
)

@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    import time

    path = request.url.path
    if path in _RATE_LIMIT_EXEMPT or path.startswith(_RATE_LIMIT_EXEMPT_PREFIXES):
        return await call_next(request)

    client_ip = request.client.host if request.client else "unknown"
    now = time.time()
    timestamps = _rate_limit_store.setdefault(client_ip, [])
    timestamps[:] = [t for t in timestamps if now - t < _RATE_LIMIT_WINDOW]
    if len(timestamps) >= _RATE_LIMIT_MAX:
        return JSONResponse(status_code=429, content={"detail": "Rate limit exceeded"})
    timestamps.append(now)
    return await call_next(request)


# ── Helpers ─────────────────────────────────────────────────────────────────

def _format_wei(wei: str, chain: str = "sepolia") -> str:
    """Convert wei/smallest-unit string to a human-readable amount."""
    try:
        from chains import get_chain
        reg = get_chain(chain)
        decimals = reg.config.decimals
        symbol = reg.config.native_asset
        amount = int(wei) / (10 ** decimals)
        return f"{amount:.6f} {symbol}"
    except (KeyError, ImportError):
        # Fallback for unknown chains
        eth = int(wei) / 1e18
        return f"{eth:.6f} ETH"


def _short_addr(addr: str) -> str:
    """Shorten an address for display: 0x1234...abcd"""
    if len(addr) >= 10:
        return f"{addr[:6]}...{addr[-4:]}"
    return addr


async def _sign_workflow(tx_id: str, req: SignRequest):
    """
    Background workflow:
    1. Request Telegram auth via user_auth
    2. If approved → sign the tx
    3. Update DB with result
    """
    try:
        auth_request_id = str(uuid.uuid4())

        # Store the auth_request_id
        db.update_status(tx_id, "pending_auth", auth_request_id=auth_request_id)

        # Build human-readable action description
        action_desc = (
            f"Sign transaction: send {_format_wei(req.value_wei, req.chain)} "
            f"to {_short_addr(req.to)} on {req.chain}"
        )
        if req.note:
            action_desc += f" — {req.note}"

        # Request auth from user_auth service (blocking poll)
        auth_status = await request_auth(
            request_id=auth_request_id,
            user_id=req.user_id,
            action=action_desc,
            telegram_chat_id=req.telegram_chat_id,
        )

        if auth_status == "approved":
            db.update_status(tx_id, "approved")
            logger.info("Tx %s approved, signing & broadcasting on %s...", tx_id, req.chain)

            try:
                result = await sign_transaction(
                    to=req.to,
                    value_wei=req.value_wei,
                    data=req.data,
                    gas_limit=req.gas_limit,
                    chain=req.chain,
                    from_address=req.from_address,
                )
                db.update_status(
                    tx_id,
                    "broadcast",
                    signed_tx_hash=result.tx_hash,
                    raw_signed_tx=result.raw_tx,
                )
                logger.info(
                    "Tx %s BROADCAST OK on %s: hash=%s  to=%s  value=%s",
                    tx_id, req.chain, result.tx_hash, result.to_address, result.value_wei,
                )
            except Exception as exc:
                reason = str(exc)
                logger.error(
                    "Tx %s BROADCAST FAILED: %s  to=%s  value=%s",
                    tx_id, reason, req.to, req.value_wei,
                )
                logger.debug("Tx %s traceback:", tx_id, exc_info=True)
                db.update_status(tx_id, "sign_failed", error_reason=reason)

        elif auth_status == "rejected":
            db.update_status(tx_id, "rejected")
            logger.info("Tx %s rejected by user", tx_id)

        else:
            # expired or unknown
            db.update_status(tx_id, "expired")
            logger.info("Tx %s auth expired/unknown (%s)", tx_id, auth_status)

    except TimeoutError:
        db.update_status(tx_id, "expired")
        logger.warning("Tx %s auth timed out", tx_id)
    except Exception as exc:
            reason = str(exc)
            logger.error("Sign workflow FAILED for tx %s: %s", tx_id, reason)
            logger.debug("Tx %s traceback:", tx_id, exc_info=True)
            db.update_status(tx_id, "sign_failed", error_reason=reason)


# ── Endpoints ───────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "wallet": WALLET_ADDRESS}


@app.get("/wallets")
async def list_wallets():
    """Return all configured wallet addresses."""
    return {"wallets": get_wallet_addresses()}


@app.post("/sign", response_model=SignResponse)
async def sign(req: SignRequest):
    """
    Submit a transaction for signing.
    Returns immediately; signing happens asynchronously after Telegram auth.
    """
    # Validate chain is registered
    try:
        from chains import get_chain
        chain_reg = get_chain(req.chain)
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # Validate address using the chain's address_regex
    if not chain_reg.config.validate_address(req.to):
        raise HTTPException(status_code=400, detail=f"Invalid recipient address for chain {req.chain}")

    # Validate amount
    try:
        if int(req.value_wei) <= 0:
            raise ValueError
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="value_wei must be a positive integer string")

    tx_id = str(uuid.uuid4())

    # Persist
    db.insert_request(
        tx_id=tx_id,
        auth_request_id="",  # will be updated by workflow
        user_id=req.user_id,
        note=req.note,
        to_address=req.to,
        value_wei=req.value_wei,
        data_hex=req.data,
        gas_limit=req.gas_limit,
        chain=req.chain,
        from_address=req.from_address,
    )
    logger.info("Sign request %s created (chain=%s, to=%s, value=%s)", tx_id, req.chain, req.to, req.value_wei)

    # Launch background workflow
    task = asyncio.create_task(_sign_workflow(tx_id, req))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    return SignResponse(
        tx_id=tx_id,
        status="pending_auth",
        message="Transaction queued — waiting for Telegram approval",
    )


@app.get("/sign/{tx_id}", response_model=TxStatusResponse)
async def get_sign_status(tx_id: str):
    """Check the status of a signing request."""
    row = db.get_request(tx_id)
    if not row:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return TxStatusResponse(
        tx_id=row["tx_id"],
        status=row["status"],
        to=row["to_address"],
        value_wei=row["value_wei"],
        user_id=row["user_id"],
        note=row["note"],
        chain=row.get("chain", "sepolia"),
        auth_request_id=row["auth_request_id"] or None,
        signed_tx_hash=row.get("signed_tx_hash"),
        raw_signed_tx=row.get("raw_signed_tx"),
        error_reason=row.get("error_reason"),
        created_at=row["created_at"],
        resolved_at=row.get("resolved_at"),
    )


@app.post("/auth/callback")
async def auth_callback(payload: AuthCallbackPayload):
    """
    Receive auth result from user_auth service (callback mode).
    This is a secondary notification — the primary flow uses polling.
    """
    logger.info(
        "Auth callback received: request_id=%s status=%s",
        payload.request_id,
        payload.status,
    )
    return {"received": True, "request_id": payload.request_id, "status": payload.status}

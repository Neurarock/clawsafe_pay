"""
FastAPI application for publisher_service.

Endpoints
---------
POST /intent            – receive a new payment intent (async processing)
GET  /intent/{id}       – poll status
GET  /health            – health check (no auth)
"""
from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

import publisher_service.config as config
import publisher_service.database as db
import publisher_service.api_users_db as api_users_db
import publisher_service.wallets_db as wallets_db
from publisher_service.injection_filter import check_injection
from publisher_service.models import IntentResponse, IntentStatusResponse, PaymentIntent
from publisher_service.orchestrator import run_intent_workflow
from publisher_service.security import (
    require_api_key,
    require_admin_key,
    check_agent_permission,
)
from publisher_service.api_user_models import (
    CreateApiUser,
    UpdateApiUser,
    ApiUserResponse,
    ApiUserCreatedResponse,
    ApiKeyRegeneratedResponse,
    ApiUserUsageResponse,
)
from publisher_service.wallet_models import (
    AddWallet,
    WalletResponse,
    WalletBalanceResponse,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s  %(message)s",
)
logger = logging.getLogger("publisher_service.app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    api_users_db.init_api_users_db()
    wallets_db.init_wallets_db()
    logger.info("Publisher service DB initialised at %s", db.DATABASE_PATH)
    # Seed the default dashboard API user from DEFAULT_PUBLISHER_API env var
    _seed_default_api_user()
    yield


def _seed_default_api_user():
    """Create a default agent backed by DEFAULT_PUBLISHER_API if not already present."""
    default_key = config.DEFAULT_PUBLISHER_API
    if not default_key:
        return
    # Check if an agent with this key already exists
    existing = api_users_db.get_api_user_by_key(default_key)
    if existing:
        logger.info("Default dashboard API user already exists: %s", existing["name"])
        return
    user = api_users_db.create_api_user(
        name="Dashboard (default)",
        allowed_assets=["*"],
        allowed_chains=["*"],
        max_amount_wei="0",
        daily_limit_wei="0",
        rate_limit=0,
        telegram_chat_id="",
        api_key_override=default_key,
    )
    logger.info("Seeded default dashboard API user: %s (key prefix: %s)", user["name"], user["api_key_prefix"])


app = FastAPI(
    title="ClawSafe Pay – Publisher Service",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Rate-limit middleware ────────────────────────────────────────────────────

_rate_limit_store: dict[str, list[float]] = {}
RATE_LIMIT_MAX = 60
RATE_LIMIT_WINDOW = 60.0


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    import time

    client_ip = request.client.host if request.client else "unknown"
    now = time.time()
    timestamps = _rate_limit_store.setdefault(client_ip, [])
    timestamps[:] = [t for t in timestamps if now - t < RATE_LIMIT_WINDOW]
    if len(timestamps) >= RATE_LIMIT_MAX:
        return JSONResponse(status_code=429, content={"detail": "Rate limit exceeded"})
    timestamps.append(now)
    return await call_next(request)


# ── Endpoints ────────────────────────────────────────────────────────────────


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/intent", response_model=IntentResponse, status_code=202)
async def submit_intent(request: Request, payload: PaymentIntent, _key=Depends(require_api_key)):
    """Accept a PaymentIntent from OpenClaw. Store it and start the workflow.

    Transactions ALWAYS require an agent API key — even from the dashboard.
    The admin key alone cannot submit transactions; it must be an agent key.
    """
    # ── Agent key required for transactions ──────────────────────────────────
    api_user = getattr(request.state, "api_user", None)
    is_admin = getattr(request.state, "is_admin", False)
    if is_admin and api_user is None:
        raise HTTPException(
            status_code=403,
            detail="Transactions require an agent API key. "
                   "The admin key cannot submit transactions directly. "
                   "Please use an agent key (create one in the Agent section).",
        )

    # ── Injection filter ─────────────────────────────────────────────────────
    filter_result = await check_injection(
        intent_id=payload.intent_id,
        from_user=payload.from_user,
        to_user=payload.to_user,
        note=payload.note,
    )
    # ── Agent permission check ────────────────────────────────────────────
    check_agent_permission(
        api_user,
        chain=payload.chain,
        asset=payload.asset,
        amount_wei=payload.amount_wei,
    )

    if filter_result.score >= config.INJECTION_BLOCK_THRESHOLD:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "injection_detected",
                "score": filter_result.score,
                "reason": filter_result.reason,
                "model_used": filter_result.model_used,
            },
        )
    if filter_result.score >= config.INJECTION_WARN_THRESHOLD:
        logger.warning(
            "Injection filter WARN intent_id=%s score=%d reason=%r model=%s",
            payload.intent_id,
            filter_result.score,
            filter_result.reason,
            filter_result.model_used,
        )

    # Duplicate check
    if db.get_intent(payload.intent_id):
        raise HTTPException(status_code=409, detail="Duplicate intent_id")

    db.insert_intent(
        intent_id=payload.intent_id,
        from_user=payload.from_user,
        to_user=payload.to_user,
        to_address=payload.to_address,
        amount_wei=payload.amount_wei,
        note=payload.note,
        chain=payload.chain,
        asset=payload.asset,
        from_address=payload.from_address,
        api_user_id=api_user["id"] if api_user else "",
    )
    logger.info("Intent %s received (from=%s to=%s chain=%s from_address=%s)", payload.intent_id, payload.from_user, payload.to_user, payload.chain, payload.from_address or 'default')

    # ── Track daily usage for agent ────────────────────────────────────────
    if api_user:
        api_users_db.record_usage(api_user["id"], payload.amount_wei)

    # Launch workflow in background — do not await
    asyncio.create_task(run_intent_workflow(payload.intent_id))

    return IntentResponse(
        intent_id=payload.intent_id,
        status="pending",
        chain=payload.chain,
        message="Intent received, processing started",
    )


@app.get("/intent/{intent_id}", response_model=IntentStatusResponse, dependencies=[Depends(require_api_key)])
async def get_intent_status(intent_id: str):
    """Poll the current state of a payment intent."""
    row = db.get_intent(intent_id)
    if not row:
        raise HTTPException(status_code=404, detail="Intent not found")

    draft_tx = json.loads(row["draft_tx_json"]) if row["draft_tx_json"] else None
    review_report = json.loads(row["review_report_json"]) if row["review_report_json"] else None

    return IntentStatusResponse(
        intent_id=row["intent_id"],
        status=row["status"],
        from_user=row["from_user"],
        to_user=row["to_user"],
        to_address=row["to_address"],
        from_address=row.get("from_address", ""),
        amount_wei=row["amount_wei"],
        chain=row.get("chain", "sepolia"),
        asset=row.get("asset", "ETH"),
        note=row["note"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        draft_tx=draft_tx,
        review_report=review_report,
        tx_hash=row["tx_hash"],
        error_message=row["error_message"],
    )


@app.get("/intents", dependencies=[Depends(require_api_key)])
async def list_intents():
    """Return all intents ordered by created_at desc (for the dashboard)."""
    rows = db.list_intents()
    results = []
    for row in rows:
        results.append({
            "intent_id": row["intent_id"],
            "status": row["status"],
            "from_user": row["from_user"],
            "to_user": row["to_user"],
            "to_address": row["to_address"],
            "from_address": row.get("from_address", ""),
            "amount_wei": row["amount_wei"],
            "chain": row.get("chain", "sepolia"),
            "asset": row.get("asset", "ETH"),
            "note": row["note"],
            "tx_hash": row["tx_hash"],
            "error_message": row["error_message"],
            "api_user_id": row.get("api_user_id", ""),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        })
    return results


@app.get("/wallets")
async def list_wallets():
    """Return all wallet addresses (DB + env-configured)."""
    db_wallets = wallets_db.get_all_addresses()
    db_default = wallets_db.get_default_address()
    # Merge: DB wallets take priority, then env-configured ones
    all_addrs = list(db_wallets)
    for addr in config.AVAILABLE_WALLETS:
        if addr.lower() not in [a.lower() for a in all_addrs]:
            all_addrs.append(addr)
    default = db_default or config.SIGNER_FROM_ADDRESS
    return {"wallets": all_addrs, "default": default}


# ── Wallet Management (admin-only) ──────────────────────────────────────────


@app.post("/wallets", response_model=WalletResponse, status_code=201,
          dependencies=[Depends(require_admin_key)])
async def add_wallet_endpoint(body: AddWallet):
    """Add a new wallet with address and private key. Admin only."""
    try:
        wallet = wallets_db.add_wallet(
            address=body.address,
            private_key=body.private_key,
            label=body.label,
            chain=body.chain,
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    logger.info("Added wallet %s (%s)", wallet["id"], wallet["address"][:10])
    return wallet


@app.get("/wallets/managed", response_model=list[WalletResponse],
         dependencies=[Depends(require_admin_key)])
async def list_managed_wallets():
    """List all DB-managed wallets (without private keys)."""
    return wallets_db.list_wallets()


@app.delete("/wallets/{wallet_id}", dependencies=[Depends(require_admin_key)])
async def delete_wallet_endpoint(wallet_id: str):
    """Delete a wallet by ID."""
    ok = wallets_db.delete_wallet(wallet_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Wallet not found")
    logger.info("Deleted wallet %s", wallet_id)
    return {"detail": "Wallet deleted"}


@app.post("/wallets/{wallet_id}/set-default", response_model=WalletResponse,
          dependencies=[Depends(require_admin_key)])
async def set_default_wallet_endpoint(wallet_id: str):
    """Set a wallet as the default sending wallet."""
    ok = wallets_db.set_default_wallet(wallet_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Wallet not found")
    wallet = wallets_db.get_wallet(wallet_id)
    return wallet


@app.get("/wallets/balances")
async def wallet_balances():
    """Fetch on-chain balances for all managed wallets via Sepolia RPC."""
    import httpx

    db_wallets = wallets_db.list_wallets()
    # Also include env-configured wallets not in DB
    env_only = []
    db_addrs_lower = {w["address"].lower() for w in db_wallets}
    for addr in config.AVAILABLE_WALLETS:
        if addr.lower() not in db_addrs_lower:
            env_only.append({"address": addr, "label": "env", "chain": "sepolia"})

    all_wallets = db_wallets + env_only
    results = []

    async with httpx.AsyncClient(timeout=10.0) as client:
        for w in all_wallets:
            address = w["address"]
            chain = w.get("chain", "sepolia")
            try:
                rpc_url = config.SEPOLIA_RPC_URL  # For now, all chains use this RPC
                resp = await client.post(
                    rpc_url,
                    json={
                        "jsonrpc": "2.0",
                        "method": "eth_getBalance",
                        "params": [address, "latest"],
                        "id": 1,
                    },
                    headers={"Content-Type": "application/json"},
                )
                data = resp.json()
                balance_hex = data.get("result", "0x0")
                balance_wei = str(int(balance_hex, 16))
                balance_eth = int(balance_hex, 16) / 1e18
                results.append({
                    "address": address,
                    "label": w.get("label", ""),
                    "chain": chain,
                    "balance_wei": balance_wei,
                    "balance_display": f"{balance_eth:.6f}",
                    "symbol": "ETH",
                })
            except Exception as e:
                logger.warning("Balance fetch failed for %s: %s", address[:10], e)
                results.append({
                    "address": address,
                    "label": w.get("label", ""),
                    "chain": chain,
                    "balance_wei": "0",
                    "balance_display": "error",
                    "symbol": "ETH",
                })

    return results


# ── API User Management (admin-only) ────────────────────────────────────────


@app.post("/api-users", response_model=ApiUserCreatedResponse, status_code=201,
          dependencies=[Depends(require_admin_key)])
async def create_api_user_endpoint(body: CreateApiUser):
    """Create a new API user (agent). Returns the API key — shown only once."""
    user = api_users_db.create_api_user(
        name=body.name,
        allowed_assets=body.allowed_assets,
        allowed_chains=body.allowed_chains,
        max_amount_wei=body.max_amount_wei,
        daily_limit_wei=body.daily_limit_wei,
        rate_limit=body.rate_limit,
        telegram_chat_id=body.telegram_chat_id,
    )
    logger.info("Created API user %s (%s)", user["id"], user["name"])
    return user


@app.get("/api-users", response_model=list[ApiUserResponse],
         dependencies=[Depends(require_admin_key)])
async def list_api_users_endpoint():
    """List all API users."""
    return api_users_db.list_api_users()


@app.get("/api-users/{user_id}", response_model=ApiUserResponse,
         dependencies=[Depends(require_admin_key)])
async def get_api_user_endpoint(user_id: str):
    """Get a single API user by ID."""
    user = api_users_db.get_api_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="API user not found")
    return user


@app.put("/api-users/{user_id}", response_model=ApiUserResponse,
         dependencies=[Depends(require_admin_key)])
async def update_api_user_endpoint(user_id: str, body: UpdateApiUser):
    """Update an API user's permissions or metadata."""
    updated = api_users_db.update_api_user(
        user_id,
        name=body.name,
        telegram_chat_id=body.telegram_chat_id,
        allowed_assets=body.allowed_assets,
        allowed_chains=body.allowed_chains,
        max_amount_wei=body.max_amount_wei,
        daily_limit_wei=body.daily_limit_wei,
        rate_limit=body.rate_limit,
        is_active=body.is_active,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="API user not found")
    logger.info("Updated API user %s", user_id)
    return updated


@app.delete("/api-users/{user_id}", dependencies=[Depends(require_admin_key)])
async def delete_api_user_endpoint(user_id: str):
    """Deactivate an API user (soft-delete)."""
    ok = api_users_db.delete_api_user(user_id)
    if not ok:
        raise HTTPException(status_code=404, detail="API user not found")
    logger.info("Deactivated API user %s", user_id)
    return {"detail": "API user deactivated"}


@app.post("/api-users/{user_id}/regenerate-key", response_model=ApiKeyRegeneratedResponse,
          dependencies=[Depends(require_admin_key)])
async def regenerate_key_endpoint(user_id: str):
    """Regenerate the API key for an existing user. Old key is invalidated."""
    result = api_users_db.regenerate_api_key(user_id)
    if not result:
        raise HTTPException(status_code=404, detail="API user not found")
    logger.info("Regenerated API key for user %s", user_id)
    return result


@app.get("/api-users/{user_id}/usage", response_model=ApiUserUsageResponse,
         dependencies=[Depends(require_admin_key)])
async def get_api_user_usage_endpoint(user_id: str):
    """Get today's usage stats for an API user."""
    user = api_users_db.get_api_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="API user not found")
    usage = api_users_db.get_daily_usage(user_id)
    daily_limit = user["daily_limit_wei"]
    remaining = "unlimited"
    if daily_limit and daily_limit != "0":
        remaining = str(max(0, int(daily_limit) - int(usage["total_wei"])))
    return {
        "id": user_id,
        "name": user["name"],
        "today_total_wei": usage["total_wei"],
        "today_request_count": usage["request_count"],
        "daily_limit_wei": daily_limit,
        "limit_remaining_wei": remaining,
    }


@app.get("/api-users/{user_id}/intents", dependencies=[Depends(require_admin_key)])
async def list_agent_intents(user_id: str):
    """List all intents submitted by a specific API user (agent)."""
    user = api_users_db.get_api_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="API user not found")
    rows = db.list_intents_by_agent(user_id)
    results = []
    for row in rows:
        results.append({
            "intent_id": row["intent_id"],
            "status": row["status"],
            "from_user": row["from_user"],
            "to_user": row["to_user"],
            "to_address": row["to_address"],
            "from_address": row.get("from_address", ""),
            "amount_wei": row["amount_wei"],
            "chain": row.get("chain", "sepolia"),
            "asset": row.get("asset", "ETH"),
            "note": row["note"],
            "tx_hash": row["tx_hash"],
            "error_message": row["error_message"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        })
    return results

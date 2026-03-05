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
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, HTMLResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware

import publisher_service.config as config
import publisher_service.database as db
import publisher_service.api_users_db as api_users_db
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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s  %(message)s",
)
logger = logging.getLogger("publisher_service.app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    api_users_db.init_api_users_db()
    logger.info("Publisher service DB initialised at %s", db.DATABASE_PATH)
    yield


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
    """Accept a PaymentIntent from OpenClaw. Store it and start the workflow."""
    # ── Injection filter ─────────────────────────────────────────────────────
    filter_result = await check_injection(
        intent_id=payload.intent_id,
        from_user=payload.from_user,
        to_user=payload.to_user,
        note=payload.note,
    )
    # ── Agent permission check ────────────────────────────────────────────
    api_user = getattr(request.state, "api_user", None)
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
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        })
    return results


@app.get("/demo", response_class=HTMLResponse)
@app.get("/dashboard", response_class=HTMLResponse)
async def demo_dashboard():
    """Serve the ClawSafe Pay interactive demo dashboard."""
    dashboard_path = Path(__file__).resolve().parent.parent / "dashboard" / "index.html"
    if not dashboard_path.exists():
        raise HTTPException(status_code=404, detail="Dashboard not found")
    return HTMLResponse(content=dashboard_path.read_text(), status_code=200)


@app.get("/wallets")
async def list_wallets():
    """Return all configured wallet addresses."""
    return {"wallets": config.AVAILABLE_WALLETS, "default": config.SIGNER_FROM_ADDRESS}


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


# ── Dashboard pages ──────────────────────────────────────────────────────────


@app.get("/dashboard/api-users", response_class=HTMLResponse)
async def api_users_dashboard():
    """Serve the API Users management dashboard."""
    page_path = Path(__file__).resolve().parent.parent / "dashboard" / "api_users.html"
    if not page_path.exists():
        raise HTTPException(status_code=404, detail="API Users dashboard not found")
    return HTMLResponse(content=page_path.read_text(), status_code=200)


@app.get("/", response_class=HTMLResponse)
async def homepage():
    """Serve the ClawSafe Pay professional homepage."""
    homepage_path = Path(__file__).resolve().parent.parent / "dashboard" / "homepage.html"
    if not homepage_path.exists():
        raise HTTPException(status_code=404, detail="Homepage not found")
    return HTMLResponse(content=homepage_path.read_text(), status_code=200)

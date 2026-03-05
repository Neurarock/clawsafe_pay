"""
FastAPI application for the user_auth service.

Endpoints
---------
POST /auth/request       – receive a new auth request from signer_service
GET  /auth/{request_id}  – poll the status of an existing request
POST /telegram/webhook   – Telegram bot webhook (inline-keyboard callbacks)
GET  /health             – simple health-check

Background
----------
A periodic task expires stale pending requests after AUTH_REQUEST_TTL_SECONDS.
"""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from user_auth import database as db
from user_auth import telegram_bot, signer_callback
from user_auth import telegram_poller, telegram_handler
from user_auth.config import AUTH_REQUEST_TTL_SECONDS
from user_auth.models import AuthRequest, AuthResponse, AuthStatusResponse, TelegramUpdate
from user_auth.security import verify_hmac

# ── Logging ─────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s  %(message)s",
)
logger = logging.getLogger("user_auth.app")


# ── Background expiry task ──────────────────────────────────────────────────

async def _expire_stale_requests():
    """Periodically mark pending requests as expired and notify signer_service."""
    while True:
        await asyncio.sleep(30)  # check every 30 seconds
        try:
            expired = db.get_pending_expired(AUTH_REQUEST_TTL_SECONDS)
            for req in expired:
                rid = req["request_id"]
                logger.info("Expiring stale request %s", rid)
                db.update_status(rid, "expired")

                # Notify signer_service
                await signer_callback.notify_signer_service(rid, "expired")
                db.mark_callback_sent(rid)

                # Edit the Telegram message if possible
                if req.get("telegram_message_id"):
                    await telegram_bot.edit_message_after_resolution(
                        req["telegram_message_id"], "expired", rid
                    )
        except Exception:
            logger.exception("Error in expiry task")


# ── App lifespan ────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    db.init_db()
    logger.info("Database initialised")
    task = asyncio.create_task(_expire_stale_requests())
    # start telegram poller (fallback when webhook isn't configured)
    stop_event = asyncio.Event()
    poller_task = asyncio.create_task(telegram_poller.run_poller(stop_event))
    yield
    # Shutdown
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    # stop poller
    stop_event.set()
    poller_task.cancel()
    try:
        await poller_task
    except asyncio.CancelledError:
        pass

app = FastAPI(
    title="ClawSafe Pay – User Auth Service",
    version="0.1.0",
    lifespan=lifespan,
)


# ── Rate-limit middleware (simple in-memory) ────────────────────────────────

_rate_limit_store: dict[str, list[float]] = {}
RATE_LIMIT_MAX = 30        # max requests …
RATE_LIMIT_WINDOW = 60.0   # … per this many seconds

@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    import time

    client_ip = request.client.host if request.client else "unknown"
    now = time.time()
    timestamps = _rate_limit_store.setdefault(client_ip, [])
    # Prune old
    timestamps[:] = [t for t in timestamps if now - t < RATE_LIMIT_WINDOW]
    if len(timestamps) >= RATE_LIMIT_MAX:
        return JSONResponse(status_code=429, content={"detail": "Rate limit exceeded"})
    timestamps.append(now)
    return await call_next(request)


# ── Endpoints ───────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/auth/request", response_model=AuthResponse)
async def create_auth_request(payload: AuthRequest):
    """
    Receive an auth request from signer_service, persist it,
    and forward it to the Telegram user.
    """
    # 1. Verify HMAC integrity
    if not verify_hmac(payload.request_id, payload.user_id, payload.action, payload.hmac_digest):
        raise HTTPException(status_code=403, detail="Invalid HMAC signature")

    # 2. Reject duplicate request_id (anti-replay)
    if db.get_request(payload.request_id):
        raise HTTPException(status_code=409, detail="Duplicate request_id – possible replay")

    # 3. Persist
    db.insert_request(
        request_id=payload.request_id,
        user_id=payload.user_id,
        action=payload.action,
        hmac_digest=payload.hmac_digest,
    )
    logger.info("Auth request %s stored (user=%s)", payload.request_id, payload.user_id)

    # 4. Send Telegram prompt
    msg_id = await telegram_bot.send_auth_prompt(payload.request_id, payload.user_id, payload.action)
    if msg_id:
        db.set_telegram_message_id(payload.request_id, msg_id)

    return AuthResponse(
        request_id=payload.request_id,
        status="pending",
        message="Auth request sent to user via Telegram",
    )


@app.get("/auth/{request_id}", response_model=AuthStatusResponse)
async def get_auth_status(request_id: str):
    """Poll the current status of an auth request."""
    req = db.get_request(request_id)
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")
    return AuthStatusResponse(
        request_id=req["request_id"],
        user_id=req["user_id"],
        action=req["action"],
        status=req["status"],
        created_at=req["created_at"],
        resolved_at=req.get("resolved_at"),
    )


@app.post("/telegram/webhook")
async def telegram_webhook(update: TelegramUpdate):
    """Receive Telegram inline-keyboard callback queries via webhook."""
    cq = update.callback_query
    if not cq:
        return {"ok": True}

    # schedule processing and return quickly so Telegram sees a fast response
    try:
        import asyncio

        asyncio.create_task(telegram_handler.process_callback(cq))
    except Exception:
        logger.exception("Failed to schedule telegram callback processing")

    return {"ok": True}

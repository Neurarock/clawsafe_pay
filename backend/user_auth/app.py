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
from user_auth import telegram_webhook_setup
from user_auth.config import (
    AUTH_REQUEST_TTL_SECONDS,
    TELEGRAM_WEBHOOK_URL,
    TELEGRAM_WEBHOOK_SECRET,
)
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
                        req["telegram_message_id"], "expired", rid,
                        chat_id_override=req.get("telegram_chat_id", ""),
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

    # Telegram: prefer webhook mode if TELEGRAM_WEBHOOK_URL is configured,
    # otherwise fall back to long-polling.
    stop_event = asyncio.Event()
    poller_task = None

    if TELEGRAM_WEBHOOK_URL:
        ok = await telegram_webhook_setup.register_webhook()
        if ok:
            logger.info("Webhook mode active — long-polling disabled")
        else:
            logger.warning("Webhook registration failed — falling back to long-polling")
            poller_task = asyncio.create_task(telegram_poller.run_poller(stop_event))
    else:
        # Ensure no stale webhook blocks getUpdates
        await telegram_webhook_setup.delete_webhook()
        poller_task = asyncio.create_task(telegram_poller.run_poller(stop_event))
        logger.info("Long-polling mode active (set TELEGRAM_WEBHOOK_URL for webhook mode)")

    yield

    # Shutdown
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    # stop poller if running
    stop_event.set()
    if poller_task:
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
        telegram_chat_id=payload.telegram_chat_id,
    )
    logger.info("Auth request %s stored (user=%s)", payload.request_id, payload.user_id)

    # 4. Send Telegram prompt
    chat_id_override = payload.telegram_chat_id or ""
    msg_id = await telegram_bot.send_auth_prompt(
        payload.request_id, payload.user_id, payload.action,
        chat_id_override=chat_id_override,
    )
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
async def telegram_webhook(update: TelegramUpdate, request: Request):
    """Receive Telegram inline-keyboard callback queries via webhook."""
    # Verify secret token if configured (prevents spoofed webhook calls)
    if TELEGRAM_WEBHOOK_SECRET:
        header_secret = request.headers.get("x-telegram-bot-api-secret-token", "")
        if header_secret != TELEGRAM_WEBHOOK_SECRET:
            logger.warning("Telegram webhook: invalid secret token")
            raise HTTPException(status_code=403, detail="Invalid secret token")

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


# ── Admin endpoints ─────────────────────────────────────────────────────────

@app.post("/admin/webhook/register")
async def admin_register_webhook(request: Request):
    """
    Register (or update) the Telegram webhook URL.

    Accepts optional JSON body: {"url": "https://..."}
    Falls back to TELEGRAM_WEBHOOK_URL from config.
    """
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass

    url = body.get("url") or TELEGRAM_WEBHOOK_URL
    if not url:
        raise HTTPException(
            status_code=400,
            detail="Provide 'url' in request body or set TELEGRAM_WEBHOOK_URL env var",
        )

    ok = await telegram_webhook_setup.register_webhook(url=url)
    if not ok:
        raise HTTPException(status_code=502, detail="Telegram API rejected webhook registration")
    return {"ok": True, "webhook_url": url, "mode": "webhook"}


@app.delete("/admin/webhook")
async def admin_delete_webhook():
    """Remove the Telegram webhook (switches bot to long-polling)."""
    ok = await telegram_webhook_setup.delete_webhook()
    if not ok:
        raise HTTPException(status_code=502, detail="Failed to remove Telegram webhook")
    return {"ok": True, "mode": "polling"}


@app.get("/admin/webhook/info")
async def admin_webhook_info():
    """Return current Telegram webhook status."""
    info = await telegram_webhook_setup.get_webhook_info()
    return {
        "url": info.get("url", ""),
        "has_custom_certificate": info.get("has_custom_certificate", False),
        "pending_update_count": info.get("pending_update_count", 0),
        "last_error_date": info.get("last_error_date"),
        "last_error_message": info.get("last_error_message"),
        "mode": "webhook" if info.get("url") else "polling",
    }

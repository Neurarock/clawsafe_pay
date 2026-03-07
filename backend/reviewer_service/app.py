"""
FastAPI application for the reviewer_service.

Endpoints
---------
POST /review    – analyse a DraftTx and return a ReviewReport
GET  /health    – simple health-check (no auth)
"""
from __future__ import annotations

import logging
import time
from collections import defaultdict

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from reviewer_service.models import ReviewRequest, ReviewReport
from reviewer_service.llm_client import review_transaction_dual
import reviewer_service.config as config

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s  %(message)s",
)
logger = logging.getLogger("reviewer_service.app")

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(title="reviewer_service", version="1.0.0")

# ── In-memory rate limiter ────────────────────────────────────────────────────
_rate_buckets: dict[str, list[float]] = defaultdict(list)


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    ip = request.client.host if request.client else "unknown"
    now = time.monotonic()
    window = config.RATE_LIMIT_WINDOW_SECONDS
    bucket = _rate_buckets[ip]
    # Evict timestamps outside the current window
    _rate_buckets[ip] = [t for t in bucket if now - t < window]
    if len(_rate_buckets[ip]) >= config.RATE_LIMIT_MAX:
        return JSONResponse(
            status_code=429,
            content={"detail": "Rate limit exceeded. Try again later."},
        )
    _rate_buckets[ip].append(now)
    return await call_next(request)


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/review", response_model=ReviewReport)
async def review(req: ReviewRequest):
    """
    Analyse a DraftTx using Z.AI GLM-5 and return a ReviewReport.

    The digest in the response is echoed from draft_tx.digest so the
    publisher can perform its consistency check.
    """
    intent_id = req.intent_id
    draft_tx = req.draft_tx
    digest = draft_tx.get("digest", "")

    logger.info(
        "Received review request: intent_id=%s digest=%s...%s base_fee=%s",
        intent_id,
        digest[:10] if digest else "?",
        digest[-6:] if digest else "?",
        req.current_base_fee_wei,
    )

    result = await review_transaction_dual(
        intent_id=intent_id,
        draft_tx=draft_tx,
        current_base_fee_wei=req.current_base_fee_wei,
        calldata_description=req.calldata_description,
    )

    report = ReviewReport(
        intent_id=intent_id,
        digest=digest,
        verdict=result["verdict"],
        reasons=result["reasons"],
        summary=result["summary"],
        gas_assessment=result["gas_assessment"],
        model_used=result.get("model_used", config.ZAI_MODEL),
        models_agreed=result.get("models_agreed"),
        individual_verdicts=result.get("individual_verdicts"),
    )

    logger.info(
        "Review complete: intent_id=%s verdict=%s models=%s agreed=%s individual=%s",
        intent_id,
        report.verdict,
        report.model_used,
        report.models_agreed,
        report.individual_verdicts,
    )
    return report

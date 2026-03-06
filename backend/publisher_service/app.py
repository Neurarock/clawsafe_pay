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
from typing import Any

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
    GeneratePolicyRequest,
    GeneratePolicyResponse,
    PolicyChatRequest,
    PolicyChatResponse,
    AgentInstructionRequest,
    AgentInstructionResponse,
)
import publisher_service.zai_policy_client as zai_policy_client
import publisher_service.zai_instruction_client as zai_instruction_client
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

FAIL_STATUSES = {"failed", "rejected", "expired", "blocked", "sign_failed"}


def _infer_tx_type(note: str) -> str:
    n = (note or "").lower()
    if any(k in n for k in ("swap", "dex", "uniswap", "sushiswap", "curve")):
        return "swap"
    if any(k in n for k in ("approve", "allowance")):
        return "approval"
    if "bridge" in n:
        return "bridge"
    if "repay" in n:
        return "repay"
    if any(k in n for k in ("borrow", "loan")):
        return "borrow"
    if "nft" in n and any(k in n for k in ("buy", "mint", "snipe")):
        return "nft_buy"
    if "nft" in n and any(k in n for k in ("sell", "list")):
        return "nft_sell"
    if any(k in n for k in ("contract", "call", "execute")):
        return "contract_call"
    return "transfer"


def _is_prepopulated_demo_row(row: dict[str, Any]) -> bool:
    note = (row.get("note") or "").strip().lower()
    intent_id = (row.get("intent_id") or "").strip().lower()
    demo_notes = {
        "dashboard demo tx",
        "dashboard demo transaction",
        "manual dashboard transfer",
        "known user transfer",
        "call demo",
        "demo call",
        "demo payment request",
    }
    return note in demo_notes or intent_id.startswith("dash-")


def _derive_trust_level(*, to_address: str, status: str, seen_before: bool) -> str:
    allow = [a.lower() for a in config.POLICY_RECIPIENT_ALLOWLIST]
    addr = (to_address or "").lower()
    has_explicit_allow = "*" not in allow
    if status == "blocked":
        return "blocked"
    if has_explicit_allow and addr in allow:
        return "whitelisted"
    if seen_before:
        return "known"
    return "new"


def _derive_risk_and_reasons(*, status: str, trust: str, amount_wei: str, tx_type: str) -> tuple[str, list[str]]:
    reasons: list[str] = []
    risk = "low"
    if status in FAIL_STATUSES:
        risk = "high"
        reasons.append("terminal_status")
    if trust == "blocked":
        risk = "high"
        reasons.append("blocked_recipient")
    elif trust == "new":
        if risk == "low":
            risk = "medium"
        reasons.append("new_recipient")
    if status in {"pending_auth", "approved", "signing"}:
        if risk == "low":
            risk = "medium"
        reasons.append("awaiting_authorization")
    try:
        amount = int(amount_wei or "0")
    except (ValueError, TypeError):
        amount = 0
    if amount > 1_000_000_000_000_000_000:  # > 1 ETH
        risk = "high"
        reasons.append("large_amount")
    elif amount > 100_000_000_000_000_000 and risk == "low":  # > 0.1 ETH
        risk = "medium"
        reasons.append("elevated_amount")
    if tx_type in {"borrow", "nft_buy", "nft_sell", "contract_call", "bridge"} and risk == "low":
        risk = "medium"
        reasons.append("complex_tx_type")
    return risk, reasons


def _build_tx_metadata(row: dict[str, Any], *, seen_before: bool) -> dict[str, Any]:
    if row.get("tx_type") and row.get("tx_purpose") and row.get("risk_level") and row.get("trust_level"):
        reasons = row.get("risk_reasons")
        if reasons is None and row.get("risk_reasons_json"):
            try:
                reasons = json.loads(row.get("risk_reasons_json", "[]"))
            except json.JSONDecodeError:
                reasons = []
        if reasons is None:
            reasons = []
        return {
            "tx_type": row.get("tx_type", "transfer"),
            "tx_purpose": row.get("tx_purpose", ""),
            "risk_level": row.get("risk_level", "low"),
            "risk_reasons": reasons,
            "trust_level": row.get("trust_level", "new"),
            "policy_decision": row.get("policy_decision", "needs_review"),
            "requires_human": bool(row.get("requires_human", True)),
        }

    tx_type = _infer_tx_type(row.get("note", ""))
    if _is_prepopulated_demo_row(row):
        purpose = (row.get("note") or "").strip()
        if purpose.lower() in {"dashboard demo tx", "dashboard demo transaction", "manual dashboard transfer"}:
            purpose = "Known user transfer"
        elif purpose.lower() in {"call demo", "demo call"}:
            purpose = "Demo payment request"
        if not purpose:
            purpose = f"{row.get('from_user', 'agent')} -> {row.get('to_user', 'recipient')}"
        return {
            "tx_type": tx_type,
            "tx_purpose": purpose,
            "risk_level": "low",
            "risk_reasons": [],
            "trust_level": "known",
            "policy_decision": "auto_allowed",
            "requires_human": False,
        }

    trust_level = _derive_trust_level(
        to_address=row.get("to_address", ""),
        status=row.get("status", ""),
        seen_before=seen_before,
    )
    risk_level, reason_codes = _derive_risk_and_reasons(
        status=row.get("status", ""),
        trust=trust_level,
        amount_wei=row.get("amount_wei", "0"),
        tx_type=tx_type,
    )
    policy_decision = "auto_allowed"
    if row.get("status") == "blocked":
        policy_decision = "blocked"
    elif risk_level in {"medium", "high"} or trust_level == "new":
        policy_decision = "needs_review"

    purpose = (row.get("note") or "").strip()
    if purpose.lower() in {"dashboard demo tx", "dashboard demo transaction", "manual dashboard transfer"}:
        purpose = "Known user transfer"
    elif purpose.lower() in {"call demo", "demo call"}:
        purpose = "Demo payment request"
    if not purpose:
        purpose = f"{row.get('from_user', 'agent')} -> {row.get('to_user', 'recipient')}"

    return {
        "tx_type": tx_type,
        "tx_purpose": purpose,
        "risk_level": risk_level,
        "risk_reasons": reason_codes,
        "trust_level": trust_level,
        "policy_decision": policy_decision,
        "requires_human": policy_decision != "auto_allowed",
    }


def _resolve_api_user_name(api_user_id: str, user_map: dict[str, str]) -> str:
    if not api_user_id:
        return "Admin Dashboard"
    return user_map.get(api_user_id, "Unknown Agent")


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
RATE_LIMIT_MAX = 300   # raised from 60 — dashboard frontend polls many endpoints from one IP
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
    user_map = {u["id"]: u["name"] for u in api_users_db.list_api_users()}
    seen_recipients: set[str] = set()
    seen_before_by_id: dict[str, bool] = {}
    for row in reversed(rows):
        addr = (row.get("to_address") or "").lower()
        seen_before_by_id[row["intent_id"]] = addr in seen_recipients
        seen_recipients.add(addr)

    results = []
    for row in rows:
        meta = _build_tx_metadata(row, seen_before=seen_before_by_id.get(row["intent_id"], False))
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
            "api_user_name": _resolve_api_user_name(row.get("api_user_id", ""), user_map),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            **meta,
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


@app.post("/api-users/generate-policy", response_model=GeneratePolicyResponse,
          dependencies=[Depends(require_admin_key)])
async def generate_policy_endpoint(body: GeneratePolicyRequest):
    """Use Z.AI GLM to suggest a policy for a new agent based on its goal."""
    if not config.ZAI_API_KEY:
        raise HTTPException(status_code=503, detail="ZAI_API_KEY is not configured on this server")
    try:
        result = await zai_policy_client.generate_policy(
            bot_goal=body.bot_goal,
            bot_type=body.bot_type,
            allowed_assets=body.allowed_assets,
            allowed_chains=body.allowed_chains,
        )
    except Exception as exc:
        logger.error("Policy generation failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"Policy generation failed: {exc}")
    logger.info("Generated policy via Z.AI model=%s", result.get("model_used"))
    return GeneratePolicyResponse(**result)


@app.post("/api-users/policy-chat", response_model=PolicyChatResponse,
          dependencies=[Depends(require_admin_key)])
async def policy_chat_endpoint(body: PolicyChatRequest):
    """Multi-turn chat with Z.AI to configure a new agent. Returns a message or a completed draft."""
    if not config.ZAI_API_KEY:
        raise HTTPException(status_code=503, detail="ZAI_API_KEY is not configured on this server")
    try:
        result = await zai_policy_client.policy_chat(
            messages=[m.model_dump() for m in body.messages],
            user_message=body.user_message,
        )
    except Exception as exc:
        logger.error("Policy chat failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"Policy chat failed: {exc}")
    return PolicyChatResponse(**result)


@app.post("/agent-instruction", response_model=AgentInstructionResponse)
async def agent_instruction_endpoint(request: Request, body: AgentInstructionRequest, _key=Depends(require_api_key)):
    """
    Multi-turn agentic instruction chat. The agent receives the user's natural-language
    instruction along with injected context (wallet balances, recent trades, policy)
    and reasons about what on-chain action to take via Z.AI GLM.

    Returns a conversational message or a structured TransactionPlan ready to submit.
    """
    if not config.ZAI_API_KEY:
        raise HTTPException(status_code=503, detail="ZAI_API_KEY is not configured on this server")

    api_user = getattr(request.state, "api_user", None)

    # ── Fetch wallet balances (ETH + known ERC-20s) ───────────────────────────
    import httpx
    wallet_balances: list[dict] = []
    if body.from_address:
        # ERC-20 tokens to check on Sepolia: symbol → (contract, decimals)
        _ERC20 = {
            "USDC": ("0x1c7D4B196Cb0C7B01d743Fbc6116a902379C7238", 6),
            "WETH": ("0xfFf9976782d46CC05630D1f6eBAb18b2324d6B14", 18),
            "DAI":  ("0x68194a729C2450ad26072b3D33ADaCbcef39D574", 18),
        }
        # balanceOf(address) selector = 0x70a08231, address padded to 32 bytes
        addr_padded = body.from_address.lower().replace("0x", "").zfill(64)
        call_data = "0x70a08231" + addr_padded

        batch = [
            {"jsonrpc": "2.0", "method": "eth_getBalance",
             "params": [body.from_address, "latest"], "id": 0},
            *[
                {"jsonrpc": "2.0", "method": "eth_call",
                 "params": [{"to": token_info[0], "data": call_data}, "latest"], "id": idx + 1}
                for idx, token_info in enumerate(_ERC20.values())
            ]
        ]
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.post(
                    config.SEPOLIA_RPC_URL,
                    json=batch,
                    headers={"Content-Type": "application/json"},
                )
            results = {r["id"]: r.get("result", "0x0") for r in resp.json()}
            # ETH
            bal_hex = results.get(0, "0x0")
            bal_eth = int(bal_hex, 16) / 1e18
            wallet_balances.append({"symbol": "ETH", "balance_display": f"{bal_eth:.6f}"})
            # ERC-20s — only include if balance > 0
            for idx, (symbol, (_, decimals)) in enumerate(_ERC20.items()):
                raw = results.get(idx + 1, "0x0")
                try:
                    amount = int(raw, 16) / (10 ** decimals)
                except (ValueError, TypeError):
                    amount = 0
                if amount > 0:
                    wallet_balances.append({"symbol": symbol, "balance_display": f"{amount:.4f}"})
        except Exception as exc:
            logger.warning("Balance fetch for instruction failed: %s", exc)

    # ── Fetch recent intents for this agent ───────────────────────────────────
    recent_intents: list[dict] = []
    if api_user:
        try:
            recent_intents = db.list_intents_by_agent(api_user["id"])[:5]
        except Exception:
            pass
    else:
        try:
            recent_intents = db.list_intents()[:5]
        except Exception:
            pass

    # ── Build agent policy context ────────────────────────────────────────────
    agent_policy: dict = {}
    if api_user:
        agent_policy = {
            "allowed_contracts": api_user.get("allowed_contracts", ["*"]),
            "allowed_assets":    api_user.get("allowed_assets", ["*"]),
            "max_amount_wei":    api_user.get("max_amount_wei", "0"),
            "approval_mode":     api_user.get("approval_mode", "always_human"),
        }

    # ── Call Z.AI with full context ───────────────────────────────────────────
    try:
        result = await zai_instruction_client.instruction_chat(
            messages=[m.model_dump() for m in body.messages],
            user_message=body.instruction,
            from_address=body.from_address,
            wallet_balances=wallet_balances,
            recent_intents=recent_intents,
            agent_policy=agent_policy,
        )
    except Exception as exc:
        logger.error("Instruction chat failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"Instruction chat failed: {exc}")

    return AgentInstructionResponse(
        type=result["type"],
        content=result.get("content"),
        plan=result.get("plan"),
        messages=result["messages"],
        model_used=config.ZAI_MODEL,
    )


@app.get("/agent-instruction/greeting")
async def agent_instruction_greeting():
    """Return the greeting message for the instruction chat panel."""
    return {"greeting": zai_instruction_client.greeting()}


@app.post("/api-users", response_model=ApiUserCreatedResponse, status_code=201,
          dependencies=[Depends(require_admin_key)])
async def create_api_user_endpoint(body: CreateApiUser):
    """Create a new API user (agent). Returns the API key — shown only once."""
    user = api_users_db.create_api_user(
        name=body.name,
        bot_type=body.bot_type,
        bot_goal=body.bot_goal,
        telegram_chat_id=body.telegram_chat_id,
        allowed_assets=body.allowed_assets,
        allowed_chains=body.allowed_chains,
        allowed_contracts=body.allowed_contracts,
        max_amount_wei=body.max_amount_wei,
        daily_limit_wei=body.daily_limit_wei,
        rate_limit=body.rate_limit,
        approval_mode=body.approval_mode,
        approval_threshold_wei=body.approval_threshold_wei,
        window_limit_wei=body.window_limit_wei,
        window_seconds=body.window_seconds,
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
        bot_type=body.bot_type,
        bot_goal=body.bot_goal,
        allowed_assets=body.allowed_assets,
        allowed_chains=body.allowed_chains,
        allowed_contracts=body.allowed_contracts,
        max_amount_wei=body.max_amount_wei,
        daily_limit_wei=body.daily_limit_wei,
        rate_limit=body.rate_limit,
        approval_mode=body.approval_mode,
        approval_threshold_wei=body.approval_threshold_wei,
        window_limit_wei=body.window_limit_wei,
        window_seconds=body.window_seconds,
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
    agent_name = user.get("name", "Unknown Agent")
    seen_recipients: set[str] = set()
    seen_before_by_id: dict[str, bool] = {}
    for row in reversed(rows):
        addr = (row.get("to_address") or "").lower()
        seen_before_by_id[row["intent_id"]] = addr in seen_recipients
        seen_recipients.add(addr)

    results = []
    for row in rows:
        meta = _build_tx_metadata(row, seen_before=seen_before_by_id.get(row["intent_id"], False))
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
            "api_user_id": row.get("api_user_id", user_id),
            "api_user_name": agent_name,
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            **meta,
        })
    return results

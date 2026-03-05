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
import re
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


# ── Moltbook Feed Proxy ─────────────────────────────────────────────────────

MOLTBOOK_URL = "https://www.moltbook.com"
MOLTBOOK_API = f"{MOLTBOOK_URL}/api/v1/posts"
FINANCE_KEYWORDS = re.compile(
    r"money|crypto|finance|bitcoin|btc|ethereum|eth|solana|sol|defi|"
    r"trading|market|token|wallet|stablecoin|nft|yield|liquidity|"
    r"payment|banking|usdc|usdt|swap|invest|fund|stock|price|"
    r"blockchain|ledger|mining|staking|airdrop|dao|dex|cex|"
    r"economic|monetary|capital|currency|exchange|portfolio",
    re.IGNORECASE,
)


def _format_age(iso_ts: str) -> str:
    """Convert ISO timestamp to a human-friendly '2h ago' string."""
    from datetime import datetime, timezone

    try:
        created = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        delta = datetime.now(timezone.utc) - created
        secs = int(delta.total_seconds())
        if secs < 60:
            return "just now"
        if secs < 3600:
            m = secs // 60
            return f"{m}m ago"
        if secs < 86400:
            h = secs // 3600
            return f"{h}h ago"
        d = secs // 86400
        return f"{d}d ago"
    except Exception:
        return ""


def _process_moltbook_posts(api_data: dict) -> list[dict]:
    """Transform Moltbook API response into dashboard-friendly dicts,
    filtered for finance/crypto/money relevance."""
    raw_posts = api_data.get("posts", [])
    results: list[dict] = []

    for p in raw_posts:
        title = p.get("title", "")
        content = p.get("content", "")
        author_obj = p.get("author") or {}
        submolt_obj = p.get("submolt") or {}
        submolt_name = submolt_obj.get("name", "")

        post = {
            "title": title,
            "url": f"{MOLTBOOK_URL}/post/{p.get('id', '')}",
            "author": author_obj.get("name", "unknown"),
            "karma": p.get("score") or (p.get("upvotes", 0) - p.get("downvotes", 0)),
            "comments": p.get("comment_count"),
            "submolt": f"m/{submolt_name}" if submolt_name else None,
            "age": _format_age(p.get("created_at", "")),
            "snippet": content[:160].strip() if content else "",
        }
        results.append(post)

    # Filter for finance/crypto/money topics
    filtered = [
        r for r in results
        if FINANCE_KEYWORDS.search(r["title"])
        or FINANCE_KEYWORDS.search(r.get("snippet", ""))
        or (r["submolt"] and FINANCE_KEYWORDS.search(r["submolt"]))
    ]

    # If very few finance-specific posts, return all (agents discussing
    # general topics is still relevant context for the dashboard).
    if len(filtered) < 3:
        return results[:20]

    return filtered[:20]


@app.get("/moltbook-feed")
async def moltbook_feed():
    """Proxy Moltbook posts filtered for money/crypto/finance topics."""
    import httpx

    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(MOLTBOOK_API, headers={
                "User-Agent": "ClawSafePay/1.0 Dashboard Feed",
                "Accept": "application/json",
            })
            resp.raise_for_status()
            posts = _process_moltbook_posts(resp.json())
            return JSONResponse(content=posts)
    except Exception as e:
        logger.error("Moltbook feed fetch failed: %s", e)
        return JSONResponse(content=[], status_code=200)


# ── Crypto Price Ticker Proxy ────────────────────────────────────────────────

COINGECKO_API = "https://api.coingecko.com/api/v3"


@app.get("/crypto-prices")
async def crypto_prices():
    """Proxy CoinGecko top-10 crypto prices in USD and BTC with sparkline."""
    import httpx

    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(
                f"{COINGECKO_API}/coins/markets",
                params={
                    "vs_currency": "usd",
                    "order": "market_cap_desc",
                    "per_page": 10,
                    "page": 1,
                    "sparkline": "true",
                    "price_change_percentage": "24h",
                },
                headers={
                    "User-Agent": "ClawSafePay/1.0 Dashboard",
                    "Accept": "application/json",
                },
            )
            resp.raise_for_status()
            coins = resp.json()

            # Fetch BTC price for conversion
            btc_price = None
            for c in coins:
                if c.get("id") == "bitcoin":
                    btc_price = c.get("current_price")
                    break

            # Add BTC-denominated price
            result = []
            for c in coins:
                entry = {
                    "id": c.get("id"),
                    "symbol": c.get("symbol"),
                    "name": c.get("name"),
                    "image": c.get("image"),
                    "current_price": c.get("current_price"),
                    "market_cap_rank": c.get("market_cap_rank"),
                    "price_change_percentage_24h": c.get("price_change_percentage_24h"),
                    "market_cap": c.get("market_cap"),
                    "total_volume": c.get("total_volume"),
                    "sparkline_in_7d": c.get("sparkline_in_7d"),
                }
                if btc_price and btc_price > 0 and c.get("current_price") is not None:
                    entry["btc_price"] = c["current_price"] / btc_price
                result.append(entry)

            return JSONResponse(content=result)
    except Exception as e:
        logger.error("CoinGecko fetch failed: %s", e)
        return JSONResponse(content=[], status_code=200)


# ── Crypto News Feed Proxy ───────────────────────────────────────────────────

CRYPTO_NEWS_SOURCES = {
    "coindesk": {
        "rss": "https://www.coindesk.com/arc/outboundfeeds/rss/",
        "name": "CoinDesk",
    },
    "cointelegraph": {
        "rss": "https://cointelegraph.com/rss",
        "name": "CoinTelegraph",
    },
    "binance": {
        "rss": "https://www.binance.com/en/feed/rss",
        "name": "Binance",
    },
}


def _parse_rss_items(xml_text: str, source_name: str, max_items: int = 8) -> list[dict]:
    """Parse RSS XML into article dicts. Minimal XML parsing without lxml."""
    import xml.etree.ElementTree as ET

    articles = []
    try:
        root = ET.fromstring(xml_text)
        # Standard RSS 2.0 or Atom
        items = root.findall(".//item")
        if not items:
            # Atom feeds
            ns = {"atom": "http://www.w3.org/2005/Atom"}
            items = root.findall(".//atom:entry", ns)

        for item in items[:max_items]:
            title = ""
            link = ""
            description = ""
            pub_date = ""
            author = ""
            categories = []

            for child in item:
                tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                text = (child.text or "").strip()
                if tag == "title":
                    title = text
                elif tag == "link":
                    link = text or child.get("href", "")
                elif tag == "description" or tag == "summary" or tag == "content":
                    # Strip HTML tags for snippet
                    import re as _re
                    description = _re.sub(r"<[^>]+>", "", text)[:200].strip()
                elif tag == "pubDate" or tag == "published" or tag == "updated":
                    pub_date = text
                elif tag in ("creator", "author"):
                    author = text
                    # author might have a child <name>
                    name_el = child.find("{http://www.w3.org/2005/Atom}name") if "}" in child.tag else child.find("name")
                    if name_el is not None and name_el.text:
                        author = name_el.text.strip()
                elif tag == "category":
                    if text:
                        categories.append(text)
                    term = child.get("term", "")
                    if term and term not in categories:
                        categories.append(term)

            if not title:
                continue

            articles.append({
                "title": title,
                "url": link,
                "snippet": description[:160] if description else "",
                "source": source_name,
                "author": author,
                "age": _format_age(pub_date) if pub_date else "",
                "tags": categories[:4],
            })
    except Exception as e:
        logger.warning("RSS parse error for %s: %s", source_name, e)

    return articles


@app.get("/crypto-news")
async def crypto_news():
    """Aggregate crypto news from CoinDesk, CoinTelegraph, and Binance RSS feeds."""
    import httpx

    all_articles: list[dict] = []

    async with httpx.AsyncClient(timeout=12.0, follow_redirects=True) as client:
        for key, source in CRYPTO_NEWS_SOURCES.items():
            try:
                resp = await client.get(source["rss"], headers={
                    "User-Agent": "ClawSafePay/1.0 News Aggregator",
                    "Accept": "application/rss+xml, application/xml, text/xml, */*",
                })
                resp.raise_for_status()
                articles = _parse_rss_items(resp.text, source["name"])
                all_articles.extend(articles)
            except Exception as e:
                logger.warning("Crypto news fetch failed for %s: %s", key, e)

    # Sort by recency (articles with 'age' containing smaller time units first)
    def _age_sort_key(a):
        age = a.get("age", "")
        if "just now" in age:
            return 0
        if "m ago" in age:
            try:
                return int(age.replace("m ago", ""))
            except ValueError:
                return 999
        if "h ago" in age:
            try:
                return int(age.replace("h ago", "")) * 60
            except ValueError:
                return 9999
        if "d ago" in age:
            try:
                return int(age.replace("d ago", "")) * 1440
            except ValueError:
                return 99999
        return 99999

    all_articles.sort(key=_age_sort_key)
    return JSONResponse(content=all_articles[:20])

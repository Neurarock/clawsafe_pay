"""
FastAPI application for the dashboard frontend service.

Serves the ClawSafe Pay dashboard pages, static assets, and feed proxy
endpoints (crypto prices, crypto news, Moltbook) on port 8008.
API calls from the browser go cross-origin to publisher_service.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

import frontend.config as config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s  %(message)s",
)
logger = logging.getLogger("frontend.app")

_DASHBOARD_DIR = Path(__file__).resolve().parent
_SRC_DIR = _DASHBOARD_DIR / "src"

app = FastAPI(
    title="ClawSafe Pay – Dashboard",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def no_cache_static(request: Request, call_next):
    """Prevent browsers from caching stale JS/CSS after rebuilds."""
    response = await call_next(request)
    if request.url.path.startswith("/static/") or request.url.path == "/config.js":
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
    return response


# ── Health check ─────────────────────────────────────────────────────────────


@app.get("/health")
async def health():
    return {"status": "ok"}


# ── Dynamic config for frontend JS ──────────────────────────────────────────


@app.get("/config.js")
async def frontend_config():
    """Inject publisher API URL and key so the frontend knows where the backend lives."""
    js = (
        f'window.__CLAWSAFE_API = "{config.PUBLISHER_BROWSER_URL}";\n'
        f'window.__CLAWSAFE_API_KEY = "{config.PUBLISHER_API_KEY}";\n'
        f'window.__CLAWSAFE_DEFAULT_AGENT_KEY = "{config.DEFAULT_PUBLISHER_API}";\n'
    )
    return Response(content=js, media_type="application/javascript")


# ── Publisher API proxy (same-origin for browser) ───────────────────────────


@app.api_route(
    "/publisher/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
async def publisher_proxy(path: str, request: Request):
    """Proxy browser calls to publisher_service over the Docker network."""
    import httpx

    upstream = f"{config.PUBLISHER_API_URL.rstrip('/')}/{path.lstrip('/')}"
    if request.url.query:
        upstream = f"{upstream}?{request.url.query}"

    # Forward the browser's X-API-Key (agent key) when present;
    # fall back to admin key for non-transaction requests.
    browser_api_key = request.headers.get("x-api-key")
    headers = {"X-API-Key": browser_api_key or config.PUBLISHER_API_KEY}
    content_type = request.headers.get("content-type")
    if content_type:
        headers["Content-Type"] = content_type

    body = await request.body()

    try:
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            resp = await client.request(
                request.method,
                upstream,
                headers=headers,
                content=body if body else None,
            )
    except Exception as e:
        logger.error("Publisher proxy request failed: %s %s (%s)", request.method, upstream, e)
        return JSONResponse(
            status_code=502,
            content={"detail": "publisher proxy unreachable"},
        )

    media_type = resp.headers.get("content-type", "application/json")
    return Response(content=resp.content, status_code=resp.status_code, media_type=media_type)


# ── Page routes ──────────────────────────────────────────────────────────────


@app.get("/", response_class=HTMLResponse)
async def homepage():
    """Serve the ClawSafe Pay professional homepage."""
    page = _DASHBOARD_DIR / "homepage.html"
    if not page.exists():
        raise HTTPException(status_code=404, detail="Homepage not found")
    return HTMLResponse(content=page.read_text(), status_code=200)


@app.get("/demo", response_class=HTMLResponse)
@app.get("/dashboard", response_class=HTMLResponse)
async def demo_dashboard():
    """Serve the ClawSafe Pay interactive demo dashboard."""
    page = _DASHBOARD_DIR / "index.html"
    if not page.exists():
        raise HTTPException(status_code=404, detail="Dashboard not found")
    return HTMLResponse(content=page.read_text(), status_code=200)


@app.get("/setup-guide", response_class=HTMLResponse)
async def setup_guide():
    """Serve the Setup Guide page."""
    page = _DASHBOARD_DIR / "setup_guide.html"
    if not page.exists():
        raise HTTPException(status_code=404, detail="Setup Guide not found")
    return HTMLResponse(content=page.read_text(), status_code=200)


@app.get("/security", response_class=HTMLResponse)
async def security_page():
    """Serve the Security Architecture page."""
    page = _DASHBOARD_DIR / "security.html"
    if not page.exists():
        raise HTTPException(status_code=404, detail="Security page not found")
    return HTMLResponse(content=page.read_text(), status_code=200)


@app.get("/dashboard/api-users", response_class=HTMLResponse)
async def api_users_dashboard():
    """Serve the API Users management dashboard (redirect page)."""
    page = _DASHBOARD_DIR / "api_users.html"
    if not page.exists():
        raise HTTPException(status_code=404, detail="API Users dashboard not found")
    return HTMLResponse(content=page.read_text(), status_code=200)


# ── Static assets ────────────────────────────────────────────────────────────


@app.get("/dashboard/logo.png")
async def dashboard_logo():
    """Serve the dashboard logo image."""
    logo = _SRC_DIR / "logo.png"
    if not logo.exists():
        raise HTTPException(status_code=404, detail="Logo not found")
    return FileResponse(logo, media_type="image/png")


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

    filtered = [
        r for r in results
        if FINANCE_KEYWORDS.search(r["title"])
        or FINANCE_KEYWORDS.search(r.get("snippet", ""))
        or (r["submolt"] and FINANCE_KEYWORDS.search(r["submolt"]))
    ]

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

            btc_price = None
            for c in coins:
                if c.get("id") == "bitcoin":
                    btc_price = c.get("current_price")
                    break

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
        items = root.findall(".//item")
        if not items:
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
                    import re as _re
                    description = _re.sub(r"<[^>]+>", "", text)[:200].strip()
                elif tag == "pubDate" or tag == "published" or tag == "updated":
                    pub_date = text
                elif tag in ("creator", "author"):
                    author = text
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


# ── Static files mount (must be last — catch-all) ───────────────────────────
app.mount("/static", StaticFiles(directory=str(_SRC_DIR)), name="static")

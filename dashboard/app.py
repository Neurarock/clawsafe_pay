"""
FastAPI application for the dashboard frontend service.

Serves the ClawSafe Pay dashboard pages and static assets on port 8008.
All API calls are made directly from the browser to the publisher_service.
"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, FileResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

import dashboard.config as config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s  %(message)s",
)
logger = logging.getLogger("dashboard.app")

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


# ── Health check ─────────────────────────────────────────────────────────────


@app.get("/health")
async def health():
    return {"status": "ok"}


# ── Dynamic config for frontend JS ──────────────────────────────────────────


@app.get("/config.js")
async def frontend_config():
    """Inject publisher API URL and key so the frontend knows where the backend lives."""
    js = (
        f'window.__CLAWSAFE_API = "{config.PUBLISHER_API_URL}";\n'
        f'window.__CLAWSAFE_API_KEY = "{config.PUBLISHER_API_KEY}";\n'
    )
    return Response(content=js, media_type="application/javascript")


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


# Mount static files last (catch-all)
app.mount("/static", StaticFiles(directory=str(_SRC_DIR)), name="static")

"""
Configuration for the dashboard frontend service.
Loads from .env at the project root.
"""
from __future__ import annotations

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# ── Service ──────────────────────────────────────────────────────────────────
DASHBOARD_PORT: int = int(os.getenv("DASHBOARD_PORT", "8008"))

# ── Publisher API (backend) ──────────────────────────────────────────────────
PUBLISHER_API_URL: str = os.getenv("PUBLISHER_API_URL", "http://localhost:8002")
PUBLISHER_API_KEY: str = os.getenv("PUBLISHER_API_KEY", "change-me-publisher-key")

# Browser-visible URL — defaults to same-origin proxy to avoid browser reachability
# issues when publisher is only available on the Docker network.
PUBLISHER_BROWSER_URL: str = os.getenv("PUBLISHER_BROWSER_URL", "/publisher")

# Default agent API key for the dashboard user
DEFAULT_PUBLISHER_API: str = os.getenv("DEFAULT_PUBLISHER_API", "")

# ── User Auth (backend) ─────────────────────────────────────────────────────
# Used to proxy Telegram webhook and admin calls through the frontend,
# so a single ngrok / public URL can serve everything.
USER_AUTH_INTERNAL_URL: str = os.getenv("USER_AUTH_INTERNAL_URL", "http://localhost:8000")

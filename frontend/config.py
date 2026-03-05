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

# Browser-visible URL — defaults to PUBLISHER_API_URL (fine for local dev).
# In Docker the internal hostname (http://publisher:8002) is unreachable from
# the browser, so set this to the host-mapped URL (http://localhost:8002).
PUBLISHER_BROWSER_URL: str = os.getenv("PUBLISHER_BROWSER_URL", PUBLISHER_API_URL)

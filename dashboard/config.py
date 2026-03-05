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

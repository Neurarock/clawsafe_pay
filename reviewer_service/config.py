"""
Configuration for the reviewer_service.
Loads from .env at the project root.
"""
from __future__ import annotations

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# ── Service ───────────────────────────────────────────────────────────────────
REVIEWER_SERVICE_PORT: int = int(os.getenv("REVIEWER_SERVICE_PORT", "8003"))

# ── Z.AI / GLM ───────────────────────────────────────────────────────────────
ZAI_API_KEY: str = os.getenv("ZAI_API_KEY", "")
ZAI_API_BASE: str = os.getenv("ZAI_API_BASE", "https://api.z.ai/api/paas/v4")
ZAI_MODEL: str = os.getenv("ZAI_MODEL", "glm-5")
ZAI_TIMEOUT_SECONDS: float = float(os.getenv("ZAI_TIMEOUT_SECONDS", "30"))

# ── Rate limiting ─────────────────────────────────────────────────────────────
RATE_LIMIT_MAX: int = int(os.getenv("REVIEWER_RATE_LIMIT_MAX", "20"))
RATE_LIMIT_WINDOW_SECONDS: int = int(os.getenv("REVIEWER_RATE_LIMIT_WINDOW", "60"))

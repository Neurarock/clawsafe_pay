"""
Configuration for the publisher_service.
Loads from .env at the project root.
"""
from __future__ import annotations

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# ── Service ──────────────────────────────────────────────────────────────────
PUBLISHER_SERVICE_PORT: int = int(os.getenv("PUBLISHER_SERVICE_PORT", "8002"))

# ── Downstream services ───────────────────────────────────────────────────────
REVIEWER_SERVICE_URL: str = os.getenv("REVIEWER_SERVICE_URL", "http://localhost:8003")
USER_AUTH_SERVICE_URL: str = os.getenv("USER_AUTH_SERVICE_URL", "http://localhost:8000")
SIGNER_SERVICE_URL: str = os.getenv("SIGNER_SERVICE_URL", "http://localhost:8001")

# ── Shared secrets ────────────────────────────────────────────────────────────
HMAC_SECRET: str = os.getenv("HMAC_SECRET", "change-me-in-production")
PUBLISHER_API_KEY: str = os.getenv("PUBLISHER_API_KEY", "change-me-publisher-key")

# ── Signer wallet ─────────────────────────────────────────────────────────────
SIGNER_FROM_ADDRESS: str = os.getenv("SIGNER_FROM_ADDRESS", "0x0000000000000000000000000000000000000000")

# ── RPC ───────────────────────────────────────────────────────────────────────
SEPOLIA_RPC_URL: str = os.getenv("SEPOLIA_RPC_URL", "https://rpc.sepolia.org")

# ── Policy overrides ──────────────────────────────────────────────────────────
POLICY_MAX_AMOUNT_WEI: int = int(os.getenv("POLICY_MAX_AMOUNT_WEI", "50000000000000000"))
_raw_allowlist: str = os.getenv("POLICY_RECIPIENT_ALLOWLIST", "*")
POLICY_RECIPIENT_ALLOWLIST: list[str] = [a.strip() for a in _raw_allowlist.split(",") if a.strip()]
POLICY_TIP_WEI: int = int(os.getenv("POLICY_TIP_WEI", "1500000000"))

# ── Approval polling ──────────────────────────────────────────────────────────
APPROVAL_POLL_INTERVAL_SECONDS: float = float(os.getenv("APPROVAL_POLL_INTERVAL_SECONDS", "3"))
APPROVAL_TIMEOUT_SECONDS: float = float(os.getenv("APPROVAL_TIMEOUT_SECONDS", "120"))

# ── Flock API (injection filter) ─────────────────────────────────────────────
FLOCK_API_KEY: str = os.getenv("FLOCK_API_KEY", "")
FLOCK_MODEL: str = os.getenv("FLOCK_MODEL", "gemini-3-flash-preview")
# Score >= this threshold (and < block threshold) is suspicious but allowed.
INJECTION_WARN_THRESHOLD: int = int(os.getenv("INJECTION_WARN_THRESHOLD", "5"))
# Score >= this threshold → request is rejected (0-10 scale)
INJECTION_BLOCK_THRESHOLD: int = int(os.getenv("INJECTION_BLOCK_THRESHOLD", "8"))

# ── Database ──────────────────────────────────────────────────────────────────
DATABASE_PATH: str = os.getenv(
    "PUBLISHER_DATABASE_PATH",
    str(Path(__file__).resolve().parent / "intents.db"),
)

"""
Configuration for the signer_service.
Loads from environment variables via the project root .env.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# ── Wallet ──────────────────────────────────────────────────────────────────
WALLET_ADDRESS: str = os.getenv("WALLET_ADDR_1", "")
WALLET_PRIVATE_KEY: str = os.getenv("WALLET_PRIV_KEY_1", "")

# ── Ethereum RPC ────────────────────────────────────────────────────────────
SEPOLIA_RPC_URL: str = os.getenv(
    "SEPOLIA_RPC_URL",
    "https://ethereum-sepolia-rpc.publicnode.com",
)

# ── user_auth service ──────────────────────────────────────────────────────
USER_AUTH_URL: str = os.getenv("USER_AUTH_URL", "http://localhost:8000")

# ── HMAC shared secret (must match user_auth) ──────────────────────────────
HMAC_SECRET: str = os.getenv("HMAC_SECRET", "change-me-in-production")

# ── Service ─────────────────────────────────────────────────────────────────
SIGNER_SERVICE_HOST: str = os.getenv("SIGNER_SERVICE_HOST", "0.0.0.0")
SIGNER_SERVICE_PORT: int = int(os.getenv("SIGNER_SERVICE_PORT", "8001"))

# ── Database ────────────────────────────────────────────────────────────────
SIGNER_DB_PATH: str = os.getenv(
    "SIGNER_DB_PATH",
    str(Path(__file__).resolve().parent / "signer.db"),
)

# ── Timeouts ────────────────────────────────────────────────────────────────
AUTH_POLL_INTERVAL_SECONDS: float = float(os.getenv("AUTH_POLL_INTERVAL_SECONDS", "2"))
AUTH_POLL_TIMEOUT_SECONDS: float = float(os.getenv("AUTH_POLL_TIMEOUT_SECONDS", "300"))

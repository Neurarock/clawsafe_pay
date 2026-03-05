"""
Configuration for the publisher_service.
Loads from .env at the project root.
"""
from __future__ import annotations

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

# ── Service ──────────────────────────────────────────────────────────────────
PUBLISHER_SERVICE_PORT: int = int(os.getenv("PUBLISHER_SERVICE_PORT", "8002"))

# ── Downstream services ───────────────────────────────────────────────────────
REVIEWER_SERVICE_URL: str = os.getenv("REVIEWER_SERVICE_URL", "http://localhost:8003")
SIGNER_SERVICE_URL: str = os.getenv("SIGNER_SERVICE_URL", "http://localhost:8001")

# ── API key for incoming requests ─────────────────────────────────────────────
PUBLISHER_API_KEY: str = os.getenv("PUBLISHER_API_KEY", "change-me-publisher-key")

# ── Signer wallet ─────────────────────────────────────────────────────────────
SIGNER_FROM_ADDRESS: str = os.getenv("SIGNER_FROM_ADDRESS", "0x0000000000000000000000000000000000000000")
# All wallet addresses available for sending (loaded from WALLET_ADDR_N env vars)
AVAILABLE_WALLETS: list[str] = []
for _i in range(1, 20):
    _addr = os.getenv(f"WALLET_ADDR_{_i}", "")
    if _addr:
        AVAILABLE_WALLETS.append(_addr)
    else:
        break
# Ensure the default is always in the list
if SIGNER_FROM_ADDRESS and SIGNER_FROM_ADDRESS not in AVAILABLE_WALLETS:
    AVAILABLE_WALLETS.insert(0, SIGNER_FROM_ADDRESS)
# ── RPC ───────────────────────────────────────────────────────────────────────
SEPOLIA_RPC_URL: str = os.getenv("SEPOLIA_RPC_URL", "https://ethereum-sepolia-rpc.publicnode.com")

# ── Policy overrides ──────────────────────────────────────────────────────────
_raw_max = os.getenv("POLICY_MAX_AMOUNT_WEI")
POLICY_MAX_AMOUNT_WEI: int = int(_raw_max) if _raw_max else 1_000_000_000_000_000_000  # 1 ETH
_raw_allowlist: str = os.getenv("POLICY_RECIPIENT_ALLOWLIST", "*")
POLICY_RECIPIENT_ALLOWLIST: list[str] = [a.strip() for a in _raw_allowlist.split(",") if a.strip()]
POLICY_TIP_WEI: int = int(os.getenv("POLICY_TIP_WEI", "1500000000"))

# ── Signer polling ───────────────────────────────────────────────────────────
SIGNER_POLL_INTERVAL_SECONDS: float = float(os.getenv("SIGNER_POLL_INTERVAL_SECONDS", "3"))
SIGNER_POLL_TIMEOUT_SECONDS: float = float(os.getenv("SIGNER_POLL_TIMEOUT_SECONDS", "360"))

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

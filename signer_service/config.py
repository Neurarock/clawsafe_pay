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

# Multi-wallet registry: load WALLET_ADDR_N / WALLET_PRIV_KEY_N pairs
WALLETS: dict[str, str] = {}  # address (lower) -> private key
for _i in range(1, 20):  # support up to 20 wallets
    _addr = os.getenv(f"WALLET_ADDR_{_i}", "")
    _key = os.getenv(f"WALLET_PRIV_KEY_{_i}", "")
    if _addr and _key:
        WALLETS[_addr.lower()] = _key
    else:
        break

def get_wallet_addresses() -> list[str]:
    """Return all configured wallet addresses (checksummed)."""
    try:
        from web3 import Web3
        return [Web3.to_checksum_address(a) for a in WALLETS]
    except ImportError:
        return list(WALLETS.keys())

def get_private_key(address: str) -> str:
    """Look up the private key for a wallet address. Raises KeyError if not found."""
    key = WALLETS.get(address.lower())
    if not key:
        raise KeyError(f"No private key configured for wallet {address}")
    return key

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

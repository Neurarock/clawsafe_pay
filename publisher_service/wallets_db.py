"""
SQLite persistence for wallet management.

Stores wallet addresses and encrypted private keys.
Follows the same patterns as api_users_db.py.
"""
from __future__ import annotations

import base64
import hashlib
import logging
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from publisher_service.config import DATABASE_PATH

logger = logging.getLogger("publisher_service.wallets_db")

# ── Schema ───────────────────────────────────────────────────────────────────

CREATE_WALLETS_SQL = """
CREATE TABLE IF NOT EXISTS wallets (
    id              TEXT PRIMARY KEY,
    address         TEXT NOT NULL UNIQUE,
    encrypted_key   TEXT NOT NULL,
    label           TEXT NOT NULL DEFAULT '',
    chain           TEXT NOT NULL DEFAULT 'sepolia',
    is_default      INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL
);
"""

# ── Encryption helpers ───────────────────────────────────────────────────────
# Simple XOR-based obfuscation with a derived key.  *Not* a substitute for
# a proper KMS in production, but ensures private keys are never stored in
# plaintext in the SQLite file.

_ENC_SECRET = os.getenv("WALLET_ENC_SECRET", "clawsafe-default-enc-key-change-me")


def _derive_key(secret: str) -> bytes:
    """Derive a 32-byte key from the secret."""
    return hashlib.sha256(secret.encode()).digest()


def _encrypt(plaintext: str) -> str:
    """Encrypt a string and return base64-encoded ciphertext."""
    key = _derive_key(_ENC_SECRET)
    data = plaintext.encode()
    encrypted = bytes(b ^ key[i % len(key)] for i, b in enumerate(data))
    return base64.b64encode(encrypted).decode()


def _decrypt(ciphertext_b64: str) -> str:
    """Decrypt a base64-encoded ciphertext."""
    key = _derive_key(_ENC_SECRET)
    encrypted = base64.b64decode(ciphertext_b64)
    decrypted = bytes(b ^ key[i % len(key)] for i, b in enumerate(encrypted))
    return decrypted.decode()


# ── Helpers ──────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def _get_connection():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _row_to_dict(row: sqlite3.Row, default_address: str = "") -> dict:
    """Convert a Row to a safe dict (no private key)."""
    return {
        "id": row["id"],
        "address": row["address"],
        "label": row["label"],
        "chain": row["chain"],
        "is_default": bool(row["is_default"]),
        "created_at": row["created_at"],
    }


# ── Init ─────────────────────────────────────────────────────────────────────

def init_wallets_db() -> None:
    """Create the wallets table if it doesn't exist."""
    with _get_connection() as conn:
        conn.executescript(CREATE_WALLETS_SQL)
    logger.info("Wallets DB initialised")


# ── CRUD ─────────────────────────────────────────────────────────────────────

def add_wallet(
    address: str,
    private_key: str,
    label: str = "",
    chain: str = "sepolia",
) -> dict:
    """Add a new wallet. Returns the wallet dict (without private key)."""
    wallet_id = uuid4().hex[:16]
    now = _now_iso()
    encrypted = _encrypt(private_key)

    with _get_connection() as conn:
        # Check for duplicate address
        existing = conn.execute(
            "SELECT id FROM wallets WHERE LOWER(address) = LOWER(?)",
            (address,),
        ).fetchone()
        if existing:
            raise ValueError(f"Wallet with address {address} already exists")

        # If this is the first wallet, make it default
        count = conn.execute("SELECT COUNT(*) as cnt FROM wallets").fetchone()["cnt"]
        is_default = 1 if count == 0 else 0

        conn.execute(
            """INSERT INTO wallets (id, address, encrypted_key, label, chain, is_default, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (wallet_id, address, encrypted, label, chain, is_default, now),
        )

    logger.info("Added wallet %s (%s) chain=%s", wallet_id, address[:10] + "...", chain)
    return {
        "id": wallet_id,
        "address": address,
        "label": label,
        "chain": chain,
        "is_default": bool(is_default),
        "created_at": now,
    }


def list_wallets() -> list[dict]:
    """Return all wallets (without private keys)."""
    with _get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM wallets ORDER BY is_default DESC, created_at ASC"
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_wallet(wallet_id: str) -> Optional[dict]:
    """Get a single wallet by ID."""
    with _get_connection() as conn:
        row = conn.execute("SELECT * FROM wallets WHERE id = ?", (wallet_id,)).fetchone()
    return _row_to_dict(row) if row else None


def get_wallet_by_address(address: str) -> Optional[dict]:
    """Get a wallet by its address (case-insensitive)."""
    with _get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM wallets WHERE LOWER(address) = LOWER(?)", (address,)
        ).fetchone()
    return _row_to_dict(row) if row else None


def get_private_key(address: str) -> Optional[str]:
    """Retrieve the decrypted private key for a wallet address.
    Returns None if the wallet is not found."""
    with _get_connection() as conn:
        row = conn.execute(
            "SELECT encrypted_key FROM wallets WHERE LOWER(address) = LOWER(?)",
            (address,),
        ).fetchone()
    if not row:
        return None
    return _decrypt(row["encrypted_key"])


def delete_wallet(wallet_id: str) -> bool:
    """Delete a wallet by ID. Returns True if deleted."""
    with _get_connection() as conn:
        row = conn.execute("SELECT * FROM wallets WHERE id = ?", (wallet_id,)).fetchone()
        if not row:
            return False

        was_default = bool(row["is_default"])
        conn.execute("DELETE FROM wallets WHERE id = ?", (wallet_id,))

        # If the deleted wallet was default, promote the oldest remaining
        if was_default:
            remaining = conn.execute(
                "SELECT id FROM wallets ORDER BY created_at ASC LIMIT 1"
            ).fetchone()
            if remaining:
                conn.execute(
                    "UPDATE wallets SET is_default = 1 WHERE id = ?",
                    (remaining["id"],),
                )

    logger.info("Deleted wallet %s", wallet_id)
    return True


def delete_wallet_by_address(address: str) -> bool:
    """Delete a wallet by address. Returns True if deleted."""
    with _get_connection() as conn:
        row = conn.execute(
            "SELECT id FROM wallets WHERE LOWER(address) = LOWER(?)", (address,)
        ).fetchone()
    if not row:
        return False
    return delete_wallet(row["id"])


def set_default_wallet(wallet_id: str) -> bool:
    """Set a wallet as the default. Returns True if successful."""
    with _get_connection() as conn:
        row = conn.execute("SELECT id FROM wallets WHERE id = ?", (wallet_id,)).fetchone()
        if not row:
            return False
        conn.execute("UPDATE wallets SET is_default = 0")
        conn.execute("UPDATE wallets SET is_default = 1 WHERE id = ?", (wallet_id,))
    return True


def get_all_addresses() -> list[str]:
    """Return all wallet addresses (for the /wallets endpoint)."""
    with _get_connection() as conn:
        rows = conn.execute(
            "SELECT address FROM wallets ORDER BY is_default DESC, created_at ASC"
        ).fetchall()
    return [r["address"] for r in rows]


def get_default_address() -> str:
    """Return the default wallet address, or empty string if none."""
    with _get_connection() as conn:
        row = conn.execute(
            "SELECT address FROM wallets WHERE is_default = 1 LIMIT 1"
        ).fetchone()
    return row["address"] if row else ""

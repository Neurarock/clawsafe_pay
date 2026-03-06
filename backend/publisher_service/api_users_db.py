"""
SQLite persistence for API user management.

Stores API users (agents) and their permissions: allowed tokens/chains,
per-transaction limits, and daily spending caps.
"""
from __future__ import annotations

import hashlib
import json
import logging
import secrets
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from publisher_service.config import DATABASE_PATH

logger = logging.getLogger("publisher_service.api_users_db")

# ── Schema ───────────────────────────────────────────────────────────────────

CREATE_API_USERS_SQL = """
CREATE TABLE IF NOT EXISTS api_users (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    bot_type        TEXT NOT NULL DEFAULT 'personal',
    bot_goal        TEXT NOT NULL DEFAULT 'Personal bot',
    api_key_hash    TEXT NOT NULL UNIQUE,
    api_key_prefix  TEXT NOT NULL,
    telegram_chat_id TEXT NOT NULL DEFAULT '',
    allowed_assets  TEXT NOT NULL DEFAULT '["*"]',
    allowed_chains  TEXT NOT NULL DEFAULT '["*"]',
    allowed_contracts TEXT NOT NULL DEFAULT '["*"]',
    max_amount_wei  TEXT NOT NULL DEFAULT '0',
    daily_limit_wei TEXT NOT NULL DEFAULT '0',
    rate_limit      INTEGER NOT NULL DEFAULT 0,
    approval_mode   TEXT NOT NULL DEFAULT 'always_human',
    approval_threshold_wei TEXT NOT NULL DEFAULT '0',
    window_limit_wei TEXT NOT NULL DEFAULT '0',
    window_seconds  INTEGER NOT NULL DEFAULT 0,
    is_active       INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS api_user_daily_usage (
    user_id         TEXT NOT NULL,
    date_utc        TEXT NOT NULL,
    total_wei       TEXT NOT NULL DEFAULT '0',
    request_count   INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, date_utc),
    FOREIGN KEY (user_id) REFERENCES api_users(id)
);

CREATE TABLE IF NOT EXISTS api_user_usage_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         TEXT NOT NULL,
    ts_epoch        INTEGER NOT NULL,
    amount_wei      TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES api_users(id)
);

CREATE INDEX IF NOT EXISTS idx_api_user_usage_events_user_ts
ON api_user_usage_events(user_id, ts_epoch);
"""


# ── Helpers ──────────────────────────────────────────────────────────────────

def _hash_key(api_key: str) -> str:
    """SHA-256 hash of an API key for storage."""
    return hashlib.sha256(api_key.encode()).hexdigest()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


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


# ── Init ─────────────────────────────────────────────────────────────────────

def init_api_users_db() -> None:
    """Create the api_users and daily_usage tables if they don't exist."""
    with _get_connection() as conn:
        conn.executescript(CREATE_API_USERS_SQL)
        _ensure_api_users_columns(conn)
    logger.info("API users tables initialised")


def _ensure_api_users_columns(conn: sqlite3.Connection) -> None:
    """Add newly introduced columns on existing deployments."""
    existing = {
        row["name"] for row in conn.execute("PRAGMA table_info(api_users)").fetchall()
    }
    required: dict[str, str] = {
        "telegram_chat_id": "TEXT NOT NULL DEFAULT ''",
        "bot_type": "TEXT NOT NULL DEFAULT 'personal'",
        "bot_goal": "TEXT NOT NULL DEFAULT 'Personal bot'",
        "approval_mode": "TEXT NOT NULL DEFAULT 'always_human'",
        "approval_threshold_wei": "TEXT NOT NULL DEFAULT '0'",
        "window_limit_wei": "TEXT NOT NULL DEFAULT '0'",
        "window_seconds": "INTEGER NOT NULL DEFAULT 0",
        "allowed_contracts": 'TEXT NOT NULL DEFAULT \'["*"]\'',
    }
    for col, ddl in required.items():
        if col not in existing:
            conn.execute(f"ALTER TABLE api_users ADD COLUMN {col} {ddl}")


# ── CRUD ─────────────────────────────────────────────────────────────────────

def create_api_user(
    name: str,
    bot_type: str = "personal",
    bot_goal: str = "Personal bot",
    telegram_chat_id: str = "",
    allowed_assets: list[str] | None = None,
    allowed_chains: list[str] | None = None,
    allowed_contracts: list[str] | None = None,
    max_amount_wei: str = "0",
    daily_limit_wei: str = "0",
    rate_limit: int = 0,
    api_key_override: str = "",
    approval_mode: str = "always_human",
    approval_threshold_wei: str = "0",
    window_limit_wei: str = "0",
    window_seconds: int = 0,
) -> dict:
    """
    Create a new API user and return its details **including the plaintext
    API key** (shown only once).

    If api_key_override is provided, use that as the raw key instead of
    generating a new one (used for seeding the default API key).
    """
    user_id = uuid4().hex[:16]
    raw_key = api_key_override if api_key_override else f"csp_{secrets.token_urlsafe(32)}"
    key_hash = _hash_key(raw_key)
    key_prefix = raw_key[:12]
    now = _now_iso()

    assets_json     = json.dumps(allowed_assets     or ["*"])
    chains_json     = json.dumps(allowed_chains     or ["*"])
    contracts_json  = json.dumps(allowed_contracts  or ["*"])

    with _get_connection() as conn:
        conn.execute(
            """
            INSERT INTO api_users
              (id, name, bot_type, bot_goal, api_key_hash, api_key_prefix, telegram_chat_id, allowed_assets,
               allowed_chains, allowed_contracts, max_amount_wei, daily_limit_wei, rate_limit,
               approval_mode, approval_threshold_wei, window_limit_wei, window_seconds,
               is_active, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
            """,
            (user_id, name, bot_type, bot_goal, key_hash, key_prefix, telegram_chat_id, assets_json, chains_json,
             contracts_json, max_amount_wei, daily_limit_wei, rate_limit, approval_mode,
             approval_threshold_wei, window_limit_wei, window_seconds, now, now),
        )

    user = get_api_user(user_id)
    user["api_key"] = raw_key  # plaintext — only returned on creation
    return user


def get_api_user(user_id: str) -> Optional[dict]:
    with _get_connection() as conn:
        row = conn.execute("SELECT * FROM api_users WHERE id = ?", (user_id,)).fetchone()
    return _row_to_dict(row) if row else None


def get_api_user_by_key(api_key: str) -> Optional[dict]:
    """Look up an active API user by plaintext API key."""
    key_hash = _hash_key(api_key)
    with _get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM api_users WHERE api_key_hash = ? AND is_active = 1",
            (key_hash,),
        ).fetchone()
    return _row_to_dict(row) if row else None


def list_api_users() -> list[dict]:
    with _get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM api_users ORDER BY created_at DESC"
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def update_api_user(
    user_id: str,
    *,
    name: str | None = None,
    telegram_chat_id: str | None = None,
    bot_type: str | None = None,
    bot_goal: str | None = None,
    allowed_assets: list[str] | None = None,
    allowed_chains: list[str] | None = None,
    allowed_contracts: list[str] | None = None,
    max_amount_wei: str | None = None,
    daily_limit_wei: str | None = None,
    rate_limit: int | None = None,
    approval_mode: str | None = None,
    approval_threshold_wei: str | None = None,
    window_limit_wei: str | None = None,
    window_seconds: int | None = None,
    is_active: bool | None = None,
) -> Optional[dict]:
    """Update mutable fields of an API user."""
    existing = get_api_user(user_id)
    if not existing:
        return None

    updates: list[str] = []
    params: list = []

    if name is not None:
        updates.append("name = ?")
        params.append(name)
    if telegram_chat_id is not None:
        updates.append("telegram_chat_id = ?")
        params.append(telegram_chat_id)
    if bot_type is not None:
        updates.append("bot_type = ?")
        params.append(bot_type)
    if bot_goal is not None:
        updates.append("bot_goal = ?")
        params.append(bot_goal)
    if allowed_assets is not None:
        updates.append("allowed_assets = ?")
        params.append(json.dumps(allowed_assets))
    if allowed_chains is not None:
        updates.append("allowed_chains = ?")
        params.append(json.dumps(allowed_chains))
    if allowed_contracts is not None:
        updates.append("allowed_contracts = ?")
        params.append(json.dumps(allowed_contracts))
    if max_amount_wei is not None:
        updates.append("max_amount_wei = ?")
        params.append(max_amount_wei)
    if daily_limit_wei is not None:
        updates.append("daily_limit_wei = ?")
        params.append(daily_limit_wei)
    if rate_limit is not None:
        updates.append("rate_limit = ?")
        params.append(rate_limit)
    if approval_mode is not None:
        updates.append("approval_mode = ?")
        params.append(approval_mode)
    if approval_threshold_wei is not None:
        updates.append("approval_threshold_wei = ?")
        params.append(approval_threshold_wei)
    if window_limit_wei is not None:
        updates.append("window_limit_wei = ?")
        params.append(window_limit_wei)
    if window_seconds is not None:
        updates.append("window_seconds = ?")
        params.append(window_seconds)
    if is_active is not None:
        updates.append("is_active = ?")
        params.append(1 if is_active else 0)

    if not updates:
        return existing

    updates.append("updated_at = ?")
    params.append(_now_iso())
    params.append(user_id)

    with _get_connection() as conn:
        conn.execute(
            f"UPDATE api_users SET {', '.join(updates)} WHERE id = ?",
            params,
        )
    return get_api_user(user_id)


def delete_api_user(user_id: str) -> bool:
    """Soft-delete: deactivate the user."""
    with _get_connection() as conn:
        cur = conn.execute(
            "UPDATE api_users SET is_active = 0, updated_at = ? WHERE id = ?",
            (_now_iso(), user_id),
        )
    return cur.rowcount > 0


def regenerate_api_key(user_id: str) -> Optional[dict]:
    """Generate a new API key for an existing user. Returns dict with new plaintext key."""
    existing = get_api_user(user_id)
    if not existing:
        return None

    raw_key = f"csp_{secrets.token_urlsafe(32)}"
    key_hash = _hash_key(raw_key)
    key_prefix = raw_key[:12]
    now = _now_iso()

    with _get_connection() as conn:
        conn.execute(
            "UPDATE api_users SET api_key_hash = ?, api_key_prefix = ?, updated_at = ? WHERE id = ?",
            (key_hash, key_prefix, now, user_id),
        )

    user = get_api_user(user_id)
    user["api_key"] = raw_key
    return user


# ── Daily usage tracking ─────────────────────────────────────────────────────

def record_usage(user_id: str, amount_wei: str) -> None:
    """Add amount_wei to the user's daily running total."""
    today = _today_utc()
    now_ts = int(time.time())
    with _get_connection() as conn:
        row = conn.execute(
            "SELECT total_wei, request_count FROM api_user_daily_usage WHERE user_id = ? AND date_utc = ?",
            (user_id, today),
        ).fetchone()

        if row:
            new_total = str(int(row["total_wei"]) + int(amount_wei))
            new_count = row["request_count"] + 1
            conn.execute(
                "UPDATE api_user_daily_usage SET total_wei = ?, request_count = ? WHERE user_id = ? AND date_utc = ?",
                (new_total, new_count, user_id, today),
            )
        else:
            conn.execute(
                "INSERT INTO api_user_daily_usage (user_id, date_utc, total_wei, request_count) VALUES (?, ?, ?, 1)",
                (user_id, today, amount_wei),
            )
        conn.execute(
            "INSERT INTO api_user_usage_events (user_id, ts_epoch, amount_wei) VALUES (?, ?, ?)",
            (user_id, now_ts, amount_wei),
        )


def get_daily_usage(user_id: str) -> dict:
    """Return today's usage for a user."""
    today = _today_utc()
    with _get_connection() as conn:
        row = conn.execute(
            "SELECT total_wei, request_count FROM api_user_daily_usage WHERE user_id = ? AND date_utc = ?",
            (user_id, today),
        ).fetchone()
    if row:
        return {"total_wei": row["total_wei"], "request_count": row["request_count"]}
    return {"total_wei": "0", "request_count": 0}


def get_window_usage(user_id: str, window_seconds: int) -> dict:
    """Return rolling-window usage for a user."""
    if window_seconds <= 0:
        return {"total_wei": "0", "request_count": 0}
    since = int(time.time()) - int(window_seconds)
    with _get_connection() as conn:
        row = conn.execute(
            """
            SELECT COALESCE(SUM(CAST(amount_wei AS INTEGER)), 0) AS total_wei,
                   COUNT(*) AS request_count
            FROM api_user_usage_events
            WHERE user_id = ? AND ts_epoch >= ?
            """,
            (user_id, since),
        ).fetchone()
    return {
        "total_wei": str(row["total_wei"]) if row else "0",
        "request_count": int(row["request_count"]) if row else 0,
    }


# ── Internal helpers ─────────────────────────────────────────────────────────

def _row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    # Parse JSON fields
    d["allowed_assets"]     = json.loads(d.get("allowed_assets",     '["*"]'))
    d["allowed_chains"]     = json.loads(d.get("allowed_chains",     '["*"]'))
    d["allowed_contracts"]  = json.loads(d.get("allowed_contracts",  '["*"]'))
    d["bot_type"] = d.get("bot_type", "personal")
    d["bot_goal"] = d.get("bot_goal", "Personal bot")
    d["approval_mode"] = d.get("approval_mode", "always_human")
    d["approval_threshold_wei"] = d.get("approval_threshold_wei", "0")
    d["window_limit_wei"] = d.get("window_limit_wei", "0")
    d["window_seconds"] = int(d.get("window_seconds", 0) or 0)
    d["is_active"] = bool(d.get("is_active", 0))
    # Expose boolean flag for whether telegram_chat_id is set (hide actual value)
    raw_chat_id = d.pop("telegram_chat_id", "")
    d["telegram_chat_id"] = raw_chat_id  # keep for internal use
    d["telegram_chat_id_set"] = bool(raw_chat_id)
    # Never expose the hash via API
    d.pop("api_key_hash", None)
    return d

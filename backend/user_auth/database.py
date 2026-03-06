"""
Database setup and helpers for the user_auth service.
Uses SQLite via the built-in sqlite3 module for simplicity.
"""

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Optional

from user_auth.config import DATABASE_PATH

# ── Schema ──────────────────────────────────────────────────────────────────

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS auth_requests (
    request_id   TEXT PRIMARY KEY,                        -- UUID v4, supplied by signer_service
    user_id      TEXT NOT NULL,                           -- identifier of the user to authenticate
    action       TEXT NOT NULL,                           -- human-readable description of the action
    status       TEXT NOT NULL DEFAULT 'pending',         -- pending | approved | rejected | expired
    hmac_digest  TEXT NOT NULL,                           -- HMAC-SHA256 digest for request integrity
    telegram_chat_id TEXT NOT NULL DEFAULT '',            -- per-agent chat ID override
    created_at   TEXT NOT NULL,                           -- ISO-8601 UTC
    resolved_at  TEXT,                                    -- ISO-8601 UTC, set on approve/reject/expire
    telegram_message_id INTEGER,                         -- message id returned by Telegram
    callback_sent INTEGER NOT NULL DEFAULT 0             -- 1 once we notified signer_service
);
"""

# ── Lifecycle ───────────────────────────────────────────────────────────────

def init_db() -> None:
    """Create tables if they don't exist yet."""
    with _get_connection() as conn:
        conn.executescript(CREATE_TABLE_SQL)
        # Migration: add telegram_chat_id column if missing (existing DBs)
        try:
            conn.execute("ALTER TABLE auth_requests ADD COLUMN telegram_chat_id TEXT NOT NULL DEFAULT ''")
        except Exception:
            pass  # column already exists


@contextmanager
def _get_connection():
    """Yield a sqlite3 connection with row_factory set to Row."""
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


# ── CRUD helpers ────────────────────────────────────────────────────────────

def insert_request(
    request_id: str,
    user_id: str,
    action: str,
    hmac_digest: str,
    telegram_chat_id: str = "",
) -> dict:
    """Insert a new pending auth request. Returns the row as a dict."""
    now = datetime.now(timezone.utc).isoformat()
    with _get_connection() as conn:
        conn.execute(
            """
            INSERT INTO auth_requests (request_id, user_id, action, hmac_digest, telegram_chat_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (request_id, user_id, action, hmac_digest, telegram_chat_id, now),
        )
    return get_request(request_id)


def get_request(request_id: str) -> Optional[dict]:
    """Fetch a single auth request by its ID."""
    with _get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM auth_requests WHERE request_id = ?",
            (request_id,),
        ).fetchone()
    return dict(row) if row else None


def update_status(request_id: str, status: str) -> Optional[dict]:
    """Set status and resolved_at timestamp."""
    now = datetime.now(timezone.utc).isoformat()
    with _get_connection() as conn:
        conn.execute(
            """
            UPDATE auth_requests SET status = ?, resolved_at = ? WHERE request_id = ?
            """,
            (status, now, request_id),
        )
    return get_request(request_id)


def set_telegram_message_id(request_id: str, message_id: int) -> None:
    """Store the Telegram message ID for the request."""
    with _get_connection() as conn:
        conn.execute(
            "UPDATE auth_requests SET telegram_message_id = ? WHERE request_id = ?",
            (message_id, request_id),
        )


def mark_callback_sent(request_id: str) -> None:
    """Mark that we have already sent the callback to signer_service."""
    with _get_connection() as conn:
        conn.execute(
            "UPDATE auth_requests SET callback_sent = 1 WHERE request_id = ?",
            (request_id,),
        )


def get_pending_expired(ttl_seconds: int) -> list[dict]:
    """Return all pending requests whose TTL has elapsed."""
    with _get_connection() as conn:
        rows = conn.execute(
            """
            SELECT * FROM auth_requests
            WHERE status = 'pending'
              AND julianday('now') - julianday(created_at) > ? / 86400.0
            """,
            (ttl_seconds,),
        ).fetchall()
    return [dict(r) for r in rows]


# ── Standalone runner ───────────────────────────────────────────────────────

if __name__ == "__main__":
    init_db()
    print(f"Database initialised at {DATABASE_PATH}")

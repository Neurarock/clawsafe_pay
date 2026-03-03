"""
SQLite database for the signer_service.
Tracks signing requests and their lifecycle.
"""

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Optional

from signer_service.config import SIGNER_DB_PATH

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS sign_requests (
    tx_id              TEXT PRIMARY KEY,
    auth_request_id    TEXT UNIQUE,
    user_id            TEXT NOT NULL,
    note               TEXT NOT NULL DEFAULT '',
    to_address         TEXT NOT NULL,
    value_wei          TEXT NOT NULL,
    data_hex           TEXT NOT NULL DEFAULT '0x',
    gas_limit          INTEGER NOT NULL DEFAULT 21000,
    status             TEXT NOT NULL DEFAULT 'pending_auth',
    signed_tx_hash     TEXT,
    raw_signed_tx      TEXT,
    error_reason       TEXT,
    created_at         TEXT NOT NULL,
    resolved_at        TEXT
);
"""


def init_db() -> None:
    with _get_conn() as conn:
        conn.executescript(CREATE_TABLE_SQL)


@contextmanager
def _get_conn():
    conn = sqlite3.connect(SIGNER_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def insert_request(
    tx_id: str,
    auth_request_id: str,
    user_id: str,
    note: str,
    to_address: str,
    value_wei: str,
    data_hex: str,
    gas_limit: int,
) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    with _get_conn() as conn:
        conn.execute(
            """
            INSERT INTO sign_requests
                (tx_id, auth_request_id, user_id, note, to_address, value_wei, data_hex, gas_limit, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (tx_id, auth_request_id, user_id, note, to_address, value_wei, data_hex, gas_limit, now),
        )
    return get_request(tx_id)  # type: ignore[return-value]


def get_request(tx_id: str) -> Optional[dict]:
    with _get_conn() as conn:
        row = conn.execute("SELECT * FROM sign_requests WHERE tx_id = ?", (tx_id,)).fetchone()
    return dict(row) if row else None


def get_request_by_auth_id(auth_request_id: str) -> Optional[dict]:
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM sign_requests WHERE auth_request_id = ?", (auth_request_id,)
        ).fetchone()
    return dict(row) if row else None


def update_status(tx_id: str, status: str, **extra_fields) -> Optional[dict]:
    now = datetime.now(timezone.utc).isoformat()
    set_clauses = ["status = ?", "resolved_at = ?"]
    params: list = [status, now]
    for col, val in extra_fields.items():
        set_clauses.append(f"{col} = ?")
        params.append(val)
    params.append(tx_id)
    with _get_conn() as conn:
        conn.execute(
            f"UPDATE sign_requests SET {', '.join(set_clauses)} WHERE tx_id = ?",
            params,
        )
    return get_request(tx_id)


if __name__ == "__main__":
    init_db()
    print(f"Signer DB initialised at {SIGNER_DB_PATH}")

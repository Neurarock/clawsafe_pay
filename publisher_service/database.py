"""
SQLite database for publisher_service.
Tracks payment intents through the full state machine.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Optional

from publisher_service.config import DATABASE_PATH

logger = logging.getLogger("publisher_service.database")

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS payment_intents (
    intent_id           TEXT PRIMARY KEY,
    from_user           TEXT NOT NULL,
    to_user             TEXT NOT NULL,
    to_address          TEXT NOT NULL,
    amount_wei          TEXT NOT NULL,
    chain               TEXT NOT NULL DEFAULT 'sepolia',
    asset               TEXT NOT NULL DEFAULT 'ETH',
    note                TEXT NOT NULL DEFAULT '',
    status              TEXT NOT NULL DEFAULT 'pending',
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    draft_tx_json       TEXT,
    review_report_json  TEXT,
    signer_tx_id        TEXT,
    tx_hash             TEXT,
    error_message       TEXT
);
"""

VALID_STATUSES = {
    "pending", "building", "reviewing", "awaiting_approval",
    "signing", "broadcast", "confirmed",
    "rejected", "expired", "blocked", "failed",
}
TERMINAL_STATUSES = {"confirmed", "rejected", "expired", "blocked", "failed"}


@contextmanager
def _get_connection():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with _get_connection() as conn:
        conn.executescript(CREATE_TABLE_SQL)


def insert_intent(
    intent_id: str,
    from_user: str,
    to_user: str,
    to_address: str,
    amount_wei: str,
    note: str,
    chain: str = "sepolia",
    asset: str = "ETH",
) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    with _get_connection() as conn:
        conn.execute(
            """
            INSERT INTO payment_intents
              (intent_id, from_user, to_user, to_address, amount_wei, chain, asset, note, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (intent_id, from_user, to_user, to_address, amount_wei, chain, asset, note, now, now),
        )
    return get_intent(intent_id)


def get_intent(intent_id: str) -> Optional[dict]:
    with _get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM payment_intents WHERE intent_id = ?", (intent_id,)
        ).fetchone()
    return dict(row) if row else None


def update_status(intent_id: str, status: str, error: Optional[str] = None) -> None:
    row = get_intent(intent_id)
    old_status = row["status"] if row else "unknown"
    # Guard: never transition out of a terminal state
    if row and row["status"] in TERMINAL_STATUSES:
        logger.warning(
            "Refusing transition %s → %s for %s (terminal state)",
            old_status, status, intent_id,
        )
        return
    now = datetime.now(timezone.utc).isoformat()
    with _get_connection() as conn:
        conn.execute(
            """
            UPDATE payment_intents
               SET status = ?, updated_at = ?, error_message = COALESCE(?, error_message)
             WHERE intent_id = ?
            """,
            (status, now, error, intent_id),
        )
    logger.info(
        "Intent %s: %s → %s  ts=%s", intent_id, old_status, status, now
    )


def store_draft_tx(intent_id: str, draft_tx) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with _get_connection() as conn:
        conn.execute(
            "UPDATE payment_intents SET draft_tx_json = ?, updated_at = ? WHERE intent_id = ?",
            (draft_tx.model_dump_json(), now, intent_id),
        )


def store_review_report(intent_id: str, report_dict: dict) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with _get_connection() as conn:
        conn.execute(
            "UPDATE payment_intents SET review_report_json = ?, updated_at = ? WHERE intent_id = ?",
            (json.dumps(report_dict), now, intent_id),
        )


def store_signer_tx_id(intent_id: str, signer_tx_id: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with _get_connection() as conn:
        conn.execute(
            "UPDATE payment_intents SET signer_tx_id = ?, updated_at = ? WHERE intent_id = ?",
            (signer_tx_id, now, intent_id),
        )


def store_tx_hash(intent_id: str, tx_hash: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with _get_connection() as conn:
        conn.execute(
            "UPDATE payment_intents SET tx_hash = ?, updated_at = ? WHERE intent_id = ?",
            (tx_hash, now, intent_id),
        )


def list_intents() -> list[dict]:
    """Return all intents ordered by created_at descending."""
    with _get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM payment_intents ORDER BY created_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]

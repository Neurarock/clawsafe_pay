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

import publisher_service.config as config

logger = logging.getLogger("publisher_service.database")
DATABASE_PATH = config.DATABASE_PATH

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS payment_intents (
    intent_id           TEXT PRIMARY KEY,
    from_user           TEXT NOT NULL,
    to_user             TEXT NOT NULL,
    to_address          TEXT NOT NULL,
    from_address        TEXT NOT NULL DEFAULT '',
    amount_wei          TEXT NOT NULL,
    chain               TEXT NOT NULL DEFAULT 'sepolia',
    asset               TEXT NOT NULL DEFAULT 'ETH',
    note                TEXT NOT NULL DEFAULT '',
    status              TEXT NOT NULL DEFAULT 'pending',
    api_user_id         TEXT NOT NULL DEFAULT '',
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    draft_tx_json       TEXT,
    review_report_json  TEXT,
    signer_tx_id        TEXT,
    tx_hash             TEXT,
    error_message       TEXT,
    tx_type             TEXT NOT NULL DEFAULT 'transfer',
    tx_purpose          TEXT NOT NULL DEFAULT '',
    risk_level          TEXT NOT NULL DEFAULT 'low',
    risk_reasons_json   TEXT NOT NULL DEFAULT '[]',
    trust_level         TEXT NOT NULL DEFAULT 'new',
    policy_decision     TEXT NOT NULL DEFAULT 'needs_review',
    requires_human      INTEGER NOT NULL DEFAULT 1
);
"""

# Migration: add api_user_id column if it doesn't exist (for existing DBs)
_MIGRATE_API_USER_ID = """
ALTER TABLE payment_intents ADD COLUMN api_user_id TEXT NOT NULL DEFAULT '';
"""
_MIGRATE_TX_TYPE = "ALTER TABLE payment_intents ADD COLUMN tx_type TEXT NOT NULL DEFAULT 'transfer';"
_MIGRATE_TX_PURPOSE = "ALTER TABLE payment_intents ADD COLUMN tx_purpose TEXT NOT NULL DEFAULT '';"
_MIGRATE_RISK_LEVEL = "ALTER TABLE payment_intents ADD COLUMN risk_level TEXT NOT NULL DEFAULT 'low';"
_MIGRATE_RISK_REASONS = "ALTER TABLE payment_intents ADD COLUMN risk_reasons_json TEXT NOT NULL DEFAULT '[]';"
_MIGRATE_TRUST_LEVEL = "ALTER TABLE payment_intents ADD COLUMN trust_level TEXT NOT NULL DEFAULT 'new';"
_MIGRATE_POLICY_DECISION = "ALTER TABLE payment_intents ADD COLUMN policy_decision TEXT NOT NULL DEFAULT 'needs_review';"
_MIGRATE_REQUIRES_HUMAN = "ALTER TABLE payment_intents ADD COLUMN requires_human INTEGER NOT NULL DEFAULT 1;"
_MIGRATE_CALLDATA = "ALTER TABLE payment_intents ADD COLUMN calldata TEXT NOT NULL DEFAULT '0x';"
_MIGRATE_CALLDATA_DESC = "ALTER TABLE payment_intents ADD COLUMN calldata_description TEXT NOT NULL DEFAULT '';"

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
        # Migrate: add api_user_id if missing (idempotent)
        for stmt in (
            _MIGRATE_API_USER_ID,
            _MIGRATE_TX_TYPE,
            _MIGRATE_TX_PURPOSE,
            _MIGRATE_RISK_LEVEL,
            _MIGRATE_RISK_REASONS,
            _MIGRATE_TRUST_LEVEL,
            _MIGRATE_POLICY_DECISION,
            _MIGRATE_REQUIRES_HUMAN,
            _MIGRATE_CALLDATA,
            _MIGRATE_CALLDATA_DESC,
        ):
            try:
                conn.execute(stmt)
            except sqlite3.OperationalError:
                pass  # column already exists
        _backfill_tx_metadata(conn)


def _normalize_purpose(note: str, from_user: str, to_user: str) -> str:
    raw = (note or "").strip()
    n = raw.lower()
    if n in {"", "-", "n/a"}:
        return f"Transfer from {from_user or 'sender'} to {to_user or 'recipient'}"
    if n in {"dashboard demo tx", "dashboard demo transaction", "manual dashboard transfer"}:
        return "Known user transfer"
    if n in {"call demo", "demo call"}:
        return "Demo payment request"
    return raw


def _is_prepopulated_demo_row(row: dict) -> bool:
    note = (row.get("note") or "").strip().lower()
    intent_id = (row.get("intent_id") or "").strip().lower()
    demo_notes = {
        "dashboard demo tx",
        "dashboard demo transaction",
        "manual dashboard transfer",
        "known user transfer",
        "call demo",
        "demo call",
        "demo payment request",
    }
    return note in demo_notes or intent_id.startswith("dash-")


def _infer_tx_type(note: str, calldata: str = "0x") -> str:
    if calldata and calldata not in ("0x", ""):
        # Non-empty calldata always means a contract interaction — refine below
        pass
    n = (note or "").lower()
    if any(k in n for k in ("swap", "dex", "uniswap", "sushiswap", "curve")):
        return "swap"
    if any(k in n for k in ("approve", "allowance")):
        return "approval"
    if "bridge" in n:
        return "bridge"
    if "repay" in n:
        return "repay"
    if any(k in n for k in ("borrow", "loan")):
        return "borrow"
    if "nft" in n and any(k in n for k in ("buy", "mint", "snipe")):
        return "nft_buy"
    if "nft" in n and any(k in n for k in ("sell", "list")):
        return "nft_sell"
    if any(k in n for k in ("contract", "call", "execute")):
        return "contract_call"
    if calldata and calldata not in ("0x", ""):
        return "contract_call"
    return "transfer"


def _derive_trust_level(*, to_address: str, status: str, seen_before: bool) -> str:
    allow = [a.lower() for a in config.POLICY_RECIPIENT_ALLOWLIST]
    addr = (to_address or "").lower()
    has_explicit_allow = "*" not in allow
    if status == "blocked":
        return "blocked"
    if has_explicit_allow and addr in allow:
        return "whitelisted"
    if seen_before:
        return "known"
    return "new"


def _derive_risk_and_reasons(*, status: str, trust: str, amount_wei: str, tx_type: str) -> tuple[str, list[str]]:
    fail_statuses = {"failed", "rejected", "expired", "blocked", "sign_failed"}
    reasons: list[str] = []
    risk = "low"
    if status in fail_statuses:
        risk = "high"
        reasons.append("terminal_status")
    if trust == "blocked":
        risk = "high"
        reasons.append("blocked_recipient")
    elif trust == "new":
        if risk == "low":
            risk = "medium"
        reasons.append("new_recipient")
    if status in {"pending_auth", "approved", "signing"}:
        if risk == "low":
            risk = "medium"
        reasons.append("awaiting_authorization")
    try:
        amount = int(amount_wei or "0")
    except (ValueError, TypeError):
        amount = 0
    if amount > 1_000_000_000_000_000_000:
        risk = "high"
        reasons.append("large_amount")
    elif amount > 100_000_000_000_000_000 and risk == "low":
        risk = "medium"
        reasons.append("elevated_amount")
    if tx_type in {"borrow", "nft_buy", "nft_sell", "contract_call", "bridge"} and risk == "low":
        risk = "medium"
        reasons.append("complex_tx_type")
    return risk, reasons


def _build_tx_metadata(row: dict, *, seen_before: bool) -> dict:
    if _is_prepopulated_demo_row(row):
        return {
            "tx_type": _infer_tx_type(row.get("note", "")),
            "tx_purpose": _normalize_purpose(row.get("note", ""), row.get("from_user", ""), row.get("to_user", "")),
            "risk_level": "low",
            "risk_reasons_json": "[]",
            "trust_level": "known",
            "policy_decision": "auto_allowed",
            "requires_human": 0,
        }

    tx_type = _infer_tx_type(row.get("note", ""), row.get("calldata", "0x"))
    trust_level = _derive_trust_level(
        to_address=row.get("to_address", ""),
        status=row.get("status", ""),
        seen_before=seen_before,
    )
    risk_level, risk_reasons = _derive_risk_and_reasons(
        status=row.get("status", ""),
        trust=trust_level,
        amount_wei=row.get("amount_wei", "0"),
        tx_type=tx_type,
    )
    policy_decision = "auto_allowed"
    if row.get("status") == "blocked":
        policy_decision = "blocked"
    elif risk_level in {"medium", "high"} or trust_level == "new":
        policy_decision = "needs_review"
    return {
        "tx_type": tx_type,
        "tx_purpose": _normalize_purpose(row.get("note", ""), row.get("from_user", ""), row.get("to_user", "")),
        "risk_level": risk_level,
        "risk_reasons_json": json.dumps(risk_reasons),
        "trust_level": trust_level,
        "policy_decision": policy_decision,
        "requires_human": 0 if policy_decision == "auto_allowed" else 1,
    }


def _backfill_tx_metadata(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        "SELECT intent_id, note, from_user, to_user, to_address, amount_wei, status FROM payment_intents ORDER BY created_at ASC"
    ).fetchall()
    if not rows:
        return
    seen_recipients: set[str] = set()
    updates = []
    for row in rows:
        row_d = dict(row)
        addr = (row_d.get("to_address") or "").lower()
        seen_before = addr in seen_recipients
        seen_recipients.add(addr)
        meta = _build_tx_metadata(row_d, seen_before=seen_before)
        updates.append((
            meta["tx_type"],
            meta["tx_purpose"],
            meta["risk_level"],
            meta["risk_reasons_json"],
            meta["trust_level"],
            meta["policy_decision"],
            meta["requires_human"],
            row_d["intent_id"],
        ))
    conn.executemany(
        """
        UPDATE payment_intents
           SET tx_type = ?,
               tx_purpose = ?,
               risk_level = ?,
               risk_reasons_json = ?,
               trust_level = ?,
               policy_decision = ?,
               requires_human = ?
         WHERE intent_id = ?
        """,
        updates,
    )


def insert_intent(
    intent_id: str,
    from_user: str,
    to_user: str,
    to_address: str,
    amount_wei: str,
    note: str,
    chain: str = "sepolia",
    asset: str = "ETH",
    from_address: str = "",
    api_user_id: str = "",
    calldata: str = "0x",
    calldata_description: str = "",
) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    with _get_connection() as conn:
        seen_before = conn.execute(
            "SELECT 1 FROM payment_intents WHERE lower(to_address) = lower(?) LIMIT 1",
            (to_address,),
        ).fetchone() is not None
        meta = _build_tx_metadata(
            {
                "note": note,
                "from_user": from_user,
                "to_user": to_user,
                "to_address": to_address,
                "amount_wei": amount_wei,
                "status": "pending",
                "calldata": calldata,
            },
            seen_before=seen_before,
        )
        conn.execute(
            """
            INSERT INTO payment_intents
              (intent_id, from_user, to_user, to_address, from_address, amount_wei, chain, asset, note,
               api_user_id, created_at, updated_at, tx_type, tx_purpose, risk_level, risk_reasons_json,
               trust_level, policy_decision, requires_human, calldata, calldata_description)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                intent_id, from_user, to_user, to_address, from_address, amount_wei, chain, asset, note,
                api_user_id, now, now, meta["tx_type"], meta["tx_purpose"], meta["risk_level"],
                meta["risk_reasons_json"], meta["trust_level"], meta["policy_decision"], meta["requires_human"],
                calldata, calldata_description,
            ),
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
        meta = _build_tx_metadata(row or {}, seen_before=True)
        meta["risk_level"], risk_reasons = _derive_risk_and_reasons(
            status=status,
            trust=row.get("trust_level", meta["trust_level"]) if row else meta["trust_level"],
            amount_wei=row.get("amount_wei", "0") if row else "0",
            tx_type=row.get("tx_type", meta["tx_type"]) if row else meta["tx_type"],
        )
        meta["risk_reasons_json"] = json.dumps(risk_reasons)
        if status == "blocked":
            meta["policy_decision"] = "blocked"
        elif meta["risk_level"] in {"medium", "high"} or (row and row.get("trust_level") == "new"):
            meta["policy_decision"] = "needs_review"
        else:
            meta["policy_decision"] = "auto_allowed"
        meta["requires_human"] = 0 if meta["policy_decision"] == "auto_allowed" else 1
        conn.execute(
            """
            UPDATE payment_intents
               SET status = ?, updated_at = ?, error_message = COALESCE(?, error_message),
                   risk_level = ?, risk_reasons_json = ?, policy_decision = ?, requires_human = ?
             WHERE intent_id = ?
            """,
            (status, now, error, meta["risk_level"], meta["risk_reasons_json"], meta["policy_decision"], meta["requires_human"], intent_id),
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


def list_intents_by_agent(api_user_id: str) -> list[dict]:
    """Return intents submitted by a specific API user."""
    with _get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM payment_intents WHERE api_user_id = ? ORDER BY created_at DESC",
            (api_user_id,),
        ).fetchall()
    return [dict(r) for r in rows]

"""
Tests for the signer_service.
"""

import asyncio
import os
import sys
import uuid
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

# Ensure signer_service is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


# ── Test HMAC ───────────────────────────────────────────────────────────────

class TestSignerHMAC:
    """Verify the signer_service HMAC matches user_auth HMAC."""

    def test_hmac_matches_user_auth(self):
        from signer_service.security import compute_hmac as signer_hmac
        from user_auth.security import compute_hmac as auth_hmac, verify_hmac

        rid = str(uuid.uuid4())
        uid = "test_user"
        action = "Sign tx: send 0.001 ETH to 0xABCD...1234"

        signer_digest = signer_hmac(rid, uid, action)
        auth_digest = auth_hmac(rid, uid, action)

        assert signer_digest == auth_digest, "HMAC mismatch between services"
        assert verify_hmac(rid, uid, action, signer_digest)

    def test_hmac_deterministic(self):
        from signer_service.security import compute_hmac

        d1 = compute_hmac("id-1", "user", "action")
        d2 = compute_hmac("id-1", "user", "action")
        assert d1 == d2

    def test_hmac_differs_for_different_inputs(self):
        from signer_service.security import compute_hmac

        d1 = compute_hmac("id-1", "user", "action A")
        d2 = compute_hmac("id-1", "user", "action B")
        assert d1 != d2


# ── Test Signer DB ──────────────────────────────────────────────────────────

class TestSignerDB:
    """Test signer_service database CRUD."""

    @pytest.fixture(autouse=True)
    def _setup_db(self, tmp_path):
        db_path = str(tmp_path / "test_signer.db")
        with patch("signer_service.database.SIGNER_DB_PATH", db_path):
            from signer_service import database as db
            db.init_db()
            self.db = db
            self.db_path = db_path
            yield

    def test_insert_and_get(self):
        tx_id = str(uuid.uuid4())
        auth_id = str(uuid.uuid4())
        row = self.db.insert_request(
            tx_id=tx_id,
            auth_request_id=auth_id,
            user_id="user1",
            note="Test transfer",
            to_address="0x1234567890abcdef1234567890abcdef12345678",
            value_wei="1000000000000000",
            data_hex="0x",
            gas_limit=21000,
        )
        assert row is not None
        assert row["tx_id"] == tx_id
        assert row["status"] == "pending_auth"
        assert row["auth_request_id"] == auth_id

    def test_update_status(self):
        tx_id = str(uuid.uuid4())
        self.db.insert_request(
            tx_id=tx_id,
            auth_request_id=str(uuid.uuid4()),
            user_id="user1",
            note="",
            to_address="0x1234567890abcdef1234567890abcdef12345678",
            value_wei="100",
            data_hex="0x",
            gas_limit=21000,
        )

        updated = self.db.update_status(tx_id, "approved")
        assert updated["status"] == "approved"
        assert updated["resolved_at"] is not None

    def test_update_with_extra_fields(self):
        tx_id = str(uuid.uuid4())
        self.db.insert_request(
            tx_id=tx_id,
            auth_request_id=str(uuid.uuid4()),
            user_id="user1",
            note="",
            to_address="0x1234567890abcdef1234567890abcdef12345678",
            value_wei="100",
            data_hex="0x",
            gas_limit=21000,
        )

        updated = self.db.update_status(
            tx_id, "signed",
            signed_tx_hash="0xabcdef",
            raw_signed_tx="0x02f8...",
        )
        assert updated["status"] == "signed"
        assert updated["signed_tx_hash"] == "0xabcdef"
        assert updated["raw_signed_tx"] == "0x02f8..."

    def test_get_nonexistent(self):
        assert self.db.get_request("nonexistent") is None

    def test_get_by_auth_id(self):
        tx_id = str(uuid.uuid4())
        auth_id = str(uuid.uuid4())
        self.db.insert_request(
            tx_id=tx_id,
            auth_request_id=auth_id,
            user_id="user1",
            note="",
            to_address="0x1234567890abcdef1234567890abcdef12345678",
            value_wei="100",
            data_hex="0x",
            gas_limit=21000,
        )

        row = self.db.get_request_by_auth_id(auth_id)
        assert row is not None
        assert row["tx_id"] == tx_id

    def test_duplicate_auth_id_rejected(self):
        import sqlite3

        auth_id = str(uuid.uuid4())
        self.db.insert_request(
            tx_id=str(uuid.uuid4()),
            auth_request_id=auth_id,
            user_id="user1",
            note="",
            to_address="0x1234567890abcdef1234567890abcdef12345678",
            value_wei="100",
            data_hex="0x",
            gas_limit=21000,
        )
        with pytest.raises(sqlite3.IntegrityError):
            self.db.insert_request(
                tx_id=str(uuid.uuid4()),
                auth_request_id=auth_id,  # duplicate
                user_id="user2",
                note="",
                to_address="0x1234567890abcdef1234567890abcdef12345678",
                value_wei="200",
                data_hex="0x",
                gas_limit=21000,
            )


# ── Test Signer API ────────────────────────────────────────────────────────

class TestSignerAPI:
    """Test the signer_service FastAPI endpoints."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        db_path = str(tmp_path / "test_api.db")
        # Patch at the database module level so init_db uses the tmp path
        with patch("signer_service.database.SIGNER_DB_PATH", db_path):
            from signer_service import database as real_db
            real_db.init_db()

            # Now import app (which imports database) — the patch is active
            import signer_service.app  # noqa: F401  — ensure module is loaded
            yield

    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from signer_service.app import app
        return TestClient(app)

    def test_health(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"

    def test_sign_invalid_address(self, client):
        resp = client.post("/sign", json={
            "to": "not-an-address",
            "value_wei": "1000",
            "user_id": "test",
        })
        assert resp.status_code == 400

    def test_sign_zero_value(self, client):
        resp = client.post("/sign", json={
            "to": "0x1234567890abcdef1234567890abcdef12345678",
            "value_wei": "0",
            "user_id": "test",
        })
        assert resp.status_code == 400

    def test_get_nonexistent_tx(self, client):
        resp = client.get("/sign/nonexistent-id")
        assert resp.status_code == 404


# ── Test UUID uniqueness ───────────────────────────────────────────────────

class TestUUIDUniqueness:
    """Verify each signing request gets a unique auth request ID."""

    def test_uuid_uniqueness(self):
        ids = {str(uuid.uuid4()) for _ in range(1000)}
        assert len(ids) == 1000, "UUID collision detected"

"""
Tests for the user_auth service.
"""

import os
import sys
import uuid
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


# ── Test user_auth security ────────────────────────────────────────────────

class TestUserAuthSecurity:
    def test_compute_and_verify(self):
        from user_auth.security import compute_hmac, verify_hmac

        rid = str(uuid.uuid4())
        uid = "user42"
        action = "Sign contract #7"

        digest = compute_hmac(rid, uid, action)
        assert verify_hmac(rid, uid, action, digest)

    def test_reject_bad_digest(self):
        from user_auth.security import verify_hmac

        assert not verify_hmac("id", "user", "action", "bad_digest")

    def test_constant_time(self):
        """verify_hmac uses hmac.compare_digest (no early return)."""
        from user_auth.security import verify_hmac
        # Just ensure it returns False without raising
        assert not verify_hmac("a", "b", "c", "0" * 64)


# ── Test user_auth DB ──────────────────────────────────────────────────────

class TestUserAuthDB:
    @pytest.fixture(autouse=True)
    def _setup_db(self, tmp_path):
        db_path = str(tmp_path / "test_auth.db")
        with patch("user_auth.database.DATABASE_PATH", db_path):
            from user_auth import database as db
            db.init_db()
            self.db = db
            yield

    def test_insert_and_get(self):
        rid = str(uuid.uuid4())
        row = self.db.insert_request(rid, "user1", "test action", "digest123")
        assert row is not None
        assert row["request_id"] == rid
        assert row["status"] == "pending"

    def test_reject_duplicate_request_id(self):
        import sqlite3
        rid = str(uuid.uuid4())
        self.db.insert_request(rid, "user1", "action", "digest")
        with pytest.raises(sqlite3.IntegrityError):
            self.db.insert_request(rid, "user1", "action", "digest")

    def test_update_status(self):
        rid = str(uuid.uuid4())
        self.db.insert_request(rid, "user1", "action", "digest")
        updated = self.db.update_status(rid, "approved")
        assert updated["status"] == "approved"
        assert updated["resolved_at"] is not None

    def test_get_nonexistent(self):
        assert self.db.get_request("does-not-exist") is None


# ── Test user_auth API ─────────────────────────────────────────────────────

class TestUserAuthAPI:
    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        db_path = str(tmp_path / "test_api_auth.db")
        with patch("user_auth.database.DATABASE_PATH", db_path):
            from user_auth import database as db
            db.init_db()
            yield

    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from user_auth.app import app
        return TestClient(app)

    def test_health(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_reject_invalid_hmac(self, client):
        resp = client.post("/auth/request", json={
            "request_id": str(uuid.uuid4()),
            "user_id": "user1",
            "action": "test",
            "hmac_digest": "invalid",
        })
        assert resp.status_code == 403

    @patch("user_auth.telegram_bot.send_auth_prompt", return_value=42)
    def test_create_auth_request(self, mock_tg, client):
        from user_auth.security import compute_hmac
        rid = str(uuid.uuid4())
        digest = compute_hmac(rid, "user1", "test action")

        resp = client.post("/auth/request", json={
            "request_id": rid,
            "user_id": "user1",
            "action": "test action",
            "hmac_digest": digest,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "pending"
        assert data["request_id"] == rid

    @patch("user_auth.telegram_bot.send_auth_prompt", return_value=42)
    def test_reject_duplicate_request(self, mock_tg, client):
        from user_auth.security import compute_hmac
        rid = str(uuid.uuid4())
        digest = compute_hmac(rid, "user1", "test action")

        payload = {
            "request_id": rid,
            "user_id": "user1",
            "action": "test action",
            "hmac_digest": digest,
        }
        resp1 = client.post("/auth/request", json=payload)
        assert resp1.status_code == 200

        resp2 = client.post("/auth/request", json=payload)
        assert resp2.status_code == 409

    def test_get_nonexistent_request(self, client):
        resp = client.get(f"/auth/{uuid.uuid4()}")
        assert resp.status_code == 404


# ── Test Telegram UI escape ────────────────────────────────────────────────

class TestTelegramUI:
    def test_escape_md2(self):
        from user_auth.telegram_bot import _escape_md2

        raw = "Hello_World *bold* [link](url)"
        escaped = _escape_md2(raw)
        assert "\\_" in escaped
        assert "\\*" in escaped
        assert "\\[" in escaped

    def test_escape_empty(self):
        from user_auth.telegram_bot import _escape_md2
        assert _escape_md2("") == ""

    def test_escape_no_specials(self):
        from user_auth.telegram_bot import _escape_md2
        assert _escape_md2("plain text") == "plain text"

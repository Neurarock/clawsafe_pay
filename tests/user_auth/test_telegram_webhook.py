"""
Tests for Telegram webhook management.
"""

import os
import sys
import uuid
from unittest.mock import patch, AsyncMock

import httpx
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


# ── Webhook setup module ───────────────────────────────────────────────────

class TestWebhookSetup:
    """Unit tests for telegram_webhook_setup module."""

    @pytest.mark.asyncio
    async def test_register_webhook_no_url(self):
        """register_webhook returns False when no URL is provided."""
        with patch("user_auth.telegram_webhook_setup.TELEGRAM_WEBHOOK_URL", ""):
            from user_auth.telegram_webhook_setup import register_webhook
            result = await register_webhook(url="")
            assert result is False

    @pytest.mark.asyncio
    async def test_register_webhook_no_token(self):
        """register_webhook returns False when bot token is missing."""
        with patch("user_auth.telegram_webhook_setup.TELEGRAM_BOT_TOKEN", ""):
            from user_auth.telegram_webhook_setup import register_webhook
            result = await register_webhook(url="https://example.com/webhook")
            assert result is False

    @pytest.mark.asyncio
    async def test_register_webhook_success(self):
        """register_webhook returns True on Telegram API success."""
        with (
            patch("user_auth.telegram_webhook_setup.TELEGRAM_BOT_TOKEN", "TESTTOKEN"),
            patch("user_auth.telegram_webhook_setup.TELEGRAM_WEBHOOK_URL", ""),
            patch("user_auth.telegram_webhook_setup.TELEGRAM_WEBHOOK_SECRET", "secret123"),
        ):
            from user_auth.telegram_webhook_setup import register_webhook

            mock_response = httpx.Response(200, json={"ok": True, "result": True})

            with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response):
                result = await register_webhook(url="https://example.com/webhook")
            assert result is True

    @pytest.mark.asyncio
    async def test_register_webhook_failure(self):
        """register_webhook returns False on Telegram API failure."""
        with (
            patch("user_auth.telegram_webhook_setup.TELEGRAM_BOT_TOKEN", "TESTTOKEN"),
            patch("user_auth.telegram_webhook_setup.TELEGRAM_WEBHOOK_URL", ""),
            patch("user_auth.telegram_webhook_setup.TELEGRAM_WEBHOOK_SECRET", ""),
        ):
            from user_auth.telegram_webhook_setup import register_webhook

            mock_response = httpx.Response(401, json={"ok": False, "description": "Unauthorized"})

            with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response):
                result = await register_webhook(url="https://example.com/webhook")
            assert result is False

    @pytest.mark.asyncio
    async def test_delete_webhook_success(self):
        """delete_webhook returns True on success."""
        with patch("user_auth.telegram_webhook_setup.TELEGRAM_BOT_TOKEN", "TESTTOKEN"):
            from user_auth.telegram_webhook_setup import delete_webhook

            mock_response = httpx.Response(200, json={"ok": True, "result": True})

            with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response):
                result = await delete_webhook()
            assert result is True

    @pytest.mark.asyncio
    async def test_delete_webhook_no_token(self):
        """delete_webhook returns False when bot token is missing."""
        with patch("user_auth.telegram_webhook_setup.TELEGRAM_BOT_TOKEN", ""):
            from user_auth.telegram_webhook_setup import delete_webhook
            result = await delete_webhook()
            assert result is False

    @pytest.mark.asyncio
    async def test_get_webhook_info(self):
        """get_webhook_info returns the result dict."""
        with patch("user_auth.telegram_webhook_setup.TELEGRAM_BOT_TOKEN", "TESTTOKEN"):
            from user_auth.telegram_webhook_setup import get_webhook_info

            mock_response = httpx.Response(200, json={
                "ok": True,
                "result": {
                    "url": "https://example.com/webhook",
                    "pending_update_count": 0,
                },
            })

            with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_response):
                info = await get_webhook_info()
            assert info["url"] == "https://example.com/webhook"
            assert info["pending_update_count"] == 0


# ── Webhook endpoint with secret verification ──────────────────────────────

class TestWebhookEndpoint:
    """Test the /telegram/webhook endpoint with secret token verification."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        db_path = str(tmp_path / "test_webhook.db")
        with patch("user_auth.database.DATABASE_PATH", db_path):
            from user_auth import database as db
            db.init_db()
            yield

    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from user_auth.app import app
        return TestClient(app)

    def test_webhook_no_callback_query(self, client):
        """Webhook returns ok for non-callback updates."""
        resp = client.post("/telegram/webhook", json={"update_id": 1})
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    @patch("user_auth.app.TELEGRAM_WEBHOOK_SECRET", "test-secret-123")
    def test_webhook_rejects_bad_secret(self, client):
        """Webhook returns 403 when secret token doesn't match."""
        resp = client.post(
            "/telegram/webhook",
            json={"update_id": 1},
            headers={"x-telegram-bot-api-secret-token": "wrong-secret"},
        )
        assert resp.status_code == 403

    @patch("user_auth.app.TELEGRAM_WEBHOOK_SECRET", "test-secret-123")
    def test_webhook_accepts_valid_secret(self, client):
        """Webhook accepts request with valid secret token."""
        resp = client.post(
            "/telegram/webhook",
            json={"update_id": 1},
            headers={"x-telegram-bot-api-secret-token": "test-secret-123"},
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    @patch("user_auth.app.TELEGRAM_WEBHOOK_SECRET", "")
    def test_webhook_no_secret_configured(self, client):
        """When no secret is configured, skip verification."""
        resp = client.post(
            "/telegram/webhook",
            json={"update_id": 1},
        )
        assert resp.status_code == 200


# ── Admin webhook endpoints ────────────────────────────────────────────────

class TestAdminWebhookEndpoints:
    """Test admin webhook management endpoints."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        db_path = str(tmp_path / "test_admin_webhook.db")
        with patch("user_auth.database.DATABASE_PATH", db_path):
            from user_auth import database as db
            db.init_db()
            yield

    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from user_auth.app import app
        return TestClient(app)

    @patch("user_auth.telegram_webhook_setup.register_webhook", new_callable=AsyncMock, return_value=True)
    def test_register_webhook_with_url(self, mock_reg, client):
        resp = client.post(
            "/admin/webhook/register",
            json={"url": "https://example.com/telegram/webhook"},
        )
        assert resp.status_code == 200
        assert resp.json()["mode"] == "webhook"
        mock_reg.assert_called_once()

    @patch("user_auth.telegram_webhook_setup.register_webhook", new_callable=AsyncMock, return_value=False)
    def test_register_webhook_failure(self, mock_reg, client):
        resp = client.post(
            "/admin/webhook/register",
            json={"url": "https://example.com/telegram/webhook"},
        )
        assert resp.status_code == 502

    @patch("user_auth.app.TELEGRAM_WEBHOOK_URL", "")
    def test_register_webhook_no_url(self, client):
        resp = client.post("/admin/webhook/register")
        assert resp.status_code == 400

    @patch("user_auth.telegram_webhook_setup.delete_webhook", new_callable=AsyncMock, return_value=True)
    def test_delete_webhook(self, mock_del, client):
        resp = client.delete("/admin/webhook")
        assert resp.status_code == 200
        assert resp.json()["mode"] == "polling"

    @patch("user_auth.telegram_webhook_setup.get_webhook_info", new_callable=AsyncMock, return_value={
        "url": "https://example.com/webhook",
        "pending_update_count": 3,
    })
    def test_webhook_info(self, mock_info, client):
        resp = client.get("/admin/webhook/info")
        assert resp.status_code == 200
        data = resp.json()
        assert data["url"] == "https://example.com/webhook"
        assert data["pending_update_count"] == 3
        assert data["mode"] == "webhook"

    @patch("user_auth.telegram_webhook_setup.get_webhook_info", new_callable=AsyncMock, return_value={
        "url": "",
        "pending_update_count": 0,
    })
    def test_webhook_info_polling_mode(self, mock_info, client):
        resp = client.get("/admin/webhook/info")
        assert resp.status_code == 200
        assert resp.json()["mode"] == "polling"

"""
Tests for publisher_service page routes.

After the dashboard was extracted into its own service (port 8008),
the publisher_service no longer serves HTML pages or static assets.
These tests verify that the old page routes now return 404 (or are simply gone).

The actual dashboard page/asset tests live in tests/dashboard/test_pages.py.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import publisher_service.app as app_module


@pytest.fixture
def client(monkeypatch):
    """Sync TestClient with lifespan."""
    async def _noop_workflow(intent_id: str) -> None:
        return None

    monkeypatch.setattr(app_module, "run_intent_workflow", _noop_workflow)
    app_module._rate_limit_store.clear()
    with TestClient(app_module.app) as c:
        yield c


class TestPublisherNoLongerServesPages:
    """Page routes were moved to the dashboard service."""

    def test_homepage_not_served(self, client):
        resp = client.get("/")
        assert resp.status_code == 404

    def test_dashboard_not_served(self, client):
        resp = client.get("/dashboard")
        assert resp.status_code == 404

    def test_demo_not_served(self, client):
        resp = client.get("/demo")
        assert resp.status_code == 404

    def test_setup_guide_not_served(self, client):
        resp = client.get("/setup-guide")
        assert resp.status_code == 404

    def test_security_not_served(self, client):
        resp = client.get("/security")
        assert resp.status_code == 404

    def test_api_users_page_not_served(self, client):
        resp = client.get("/dashboard/api-users")
        assert resp.status_code == 404

    def test_static_assets_not_served(self, client):
        resp = client.get("/static/themes.css")
        assert resp.status_code == 404

    def test_logo_not_served(self, client):
        resp = client.get("/dashboard/logo.png")
        assert resp.status_code == 404


class TestPublisherApiStillWorks:
    """Core API endpoints remain on the publisher service."""

    def test_health_returns_200(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    def test_intents_requires_auth(self, client):
        resp = client.get("/intents")
        assert resp.status_code in (401, 403, 422)

    def test_crypto_prices_returns_200(self, client):
        resp = client.get("/crypto-prices")
        assert resp.status_code == 200

    def test_crypto_news_returns_200(self, client):
        resp = client.get("/crypto-news")
        assert resp.status_code == 200

    def test_moltbook_feed_returns_200(self, client):
        resp = client.get("/moltbook-feed")
        assert resp.status_code == 200

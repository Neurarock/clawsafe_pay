"""
Tests for publisher_service page routes.

After the dashboard was extracted into its own service (port 8008),
the publisher_service no longer serves HTML pages, static assets,
or feed proxies. These tests verify those routes now return 404.

The actual dashboard page/asset/feed tests live in tests/frontend/test_pages.py.
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

    def test_feed_proxies_not_served(self, client):
        """Feed proxy endpoints were moved to the frontend service."""
        assert client.get("/crypto-prices").status_code == 404
        assert client.get("/crypto-news").status_code == 404
        assert client.get("/moltbook-feed").status_code == 404


class TestPublisherApiStillWorks:
    """Core API endpoints remain on the publisher service."""

    def test_health_returns_200(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    def test_intents_requires_auth(self, client):
        resp = client.get("/intents")
        assert resp.status_code in (401, 403, 422)

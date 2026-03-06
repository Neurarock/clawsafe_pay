"""
Tests for the frontend service (formerly dashboard).

Covers:
- Health check
- Homepage (/)
- Setup Guide (/setup-guide)
- Security Architecture (/security)
- Dashboard (/demo, /dashboard)
- Config.js endpoint
- Static assets (/static/themes.css, /static/theme-loader.js, /dashboard/logo.png)
- API Users redirect page
- Feed proxy endpoints (/crypto-prices, /crypto-news, /moltbook-feed)
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from frontend.app import app


@pytest.fixture
def client():
    """Sync TestClient for the dashboard service."""
    with TestClient(app) as c:
        yield c


# ── Health ───────────────────────────────────────────────────────────────────

class TestHealth:
    def test_health_returns_200(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


# ── Config ───────────────────────────────────────────────────────────────────

class TestConfig:
    def test_config_js_returns_200(self, client):
        resp = client.get("/config.js")
        assert resp.status_code == 200
        assert "javascript" in resp.headers["content-type"]

    def test_config_js_contains_api_url(self, client):
        resp = client.get("/config.js")
        assert "__CLAWSAFE_API" in resp.text
        assert "/publisher" in resp.text

    def test_config_js_contains_api_key(self, client):
        resp = client.get("/config.js")
        assert "__CLAWSAFE_API_KEY" in resp.text


# ── Homepage ─────────────────────────────────────────────────────────────────

class TestHomepage:
    def test_homepage_returns_200(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]

    def test_homepage_contains_title(self, client):
        resp = client.get("/")
        assert "ClawSafe Pay" in resp.text

    def test_homepage_has_quick_start_section(self, client):
        resp = client.get("/")
        assert "Quick Start" in resp.text
        assert "quick-start" in resp.text

    def test_homepage_has_clawhub_section(self, client):
        resp = client.get("/")
        assert "ClawHub" in resp.text
        assert "clawhub.ai" in resp.text

    def test_homepage_has_nav_links_to_new_pages(self, client):
        resp = client.get("/")
        assert "/setup-guide" in resp.text
        assert "/security" in resp.text

    def test_homepage_has_theme_support(self, client):
        resp = client.get("/")
        assert "themes.css" in resp.text
        assert "theme-loader.js" in resp.text

    def test_homepage_has_features_section(self, client):
        resp = client.get("/")
        assert "Core Capabilities" in resp.text
        assert "Self-Custody" in resp.text

    def test_homepage_has_chain_pills(self, client):
        resp = client.get("/")
        for chain in ["Ethereum", "Solana", "Bitcoin", "Zcash", "Cardano"]:
            assert chain in resp.text


# ── Setup Guide ──────────────────────────────────────────────────────────────

class TestSetupGuide:
    def test_setup_guide_returns_200(self, client):
        resp = client.get("/setup-guide")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]

    def test_setup_guide_has_title(self, client):
        resp = client.get("/setup-guide")
        assert "Setup Guide" in resp.text

    def test_setup_guide_has_all_sections(self, client):
        resp = client.get("/setup-guide")
        for section in [
            "Prerequisites", "Clone", "Environment Configuration",
            "Launch Services", "Telegram Bot Setup", "Your First Transaction",
            "Adding Chains", "Production Deployment"
        ]:
            assert section in resp.text

    def test_setup_guide_has_code_blocks(self, client):
        resp = client.get("/setup-guide")
        assert "git clone" in resp.text
        assert "pip install" in resp.text

    def test_setup_guide_has_theme_support(self, client):
        resp = client.get("/setup-guide")
        assert "themes.css" in resp.text
        assert "theme-loader.js" in resp.text

    def test_setup_guide_has_nav(self, client):
        resp = client.get("/setup-guide")
        assert "/security" in resp.text
        assert "/demo" in resp.text


# ── Security Page ────────────────────────────────────────────────────────────

class TestSecurityPage:
    def test_security_returns_200(self, client):
        resp = client.get("/security")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]

    def test_security_has_title(self, client):
        resp = client.get("/security")
        assert "Security Architecture" in resp.text

    def test_security_has_all_sections(self, client):
        resp = client.get("/security")
        for section in [
            "Design Principles", "Threat Model", "Six Layers of Defence",
            "Cold Storage Architecture", "Prompt Injection Protection",
            "Policy Engine", "Inter-Service Authentication",
            "Comparison with Alternatives"
        ]:
            assert section in resp.text

    def test_security_discusses_injection_protection(self, client):
        resp = client.get("/security")
        assert "injection" in resp.text.lower()
        assert "Flock API" in resp.text
        assert "0\u201310" in resp.text or "0–10" in resp.text

    def test_security_discusses_private_key_protection(self, client):
        resp = client.get("/security")
        assert "private key" in resp.text.lower()
        assert "cold storage" in resp.text.lower()
        assert "air-gap" in resp.text.lower()

    def test_security_discusses_hmac(self, client):
        resp = client.get("/security")
        assert "HMAC" in resp.text
        assert "compare_digest" in resp.text

    def test_security_has_theme_support(self, client):
        resp = client.get("/security")
        assert "themes.css" in resp.text
        assert "theme-loader.js" in resp.text

    def test_security_comparison_table(self, client):
        resp = client.get("/security")
        assert "Custodial APIs" in resp.text
        assert "Raw Hot Wallet" in resp.text


# ── Dashboard ────────────────────────────────────────────────────────────────

class TestDashboard:
    def test_dashboard_returns_200(self, client):
        resp = client.get("/dashboard")
        assert resp.status_code == 200

    def test_demo_alias_returns_200(self, client):
        resp = client.get("/demo")
        assert resp.status_code == 200

    def test_dashboard_has_crypto_prices_widget(self, client):
        resp = client.get("/dashboard")
        assert "w-crypto-prices" in resp.text
        assert "Top 10 Crypto" in resp.text

    def test_dashboard_has_stats_row(self, client):
        resp = client.get("/dashboard")
        assert "Total Intents" in resp.text
        assert "Budget Util" in resp.text

    def test_dashboard_has_finance_widgets(self, client):
        resp = client.get("/dashboard")
        assert "Budget Tracker" in resp.text
        assert "Spend Forecast" in resp.text

    def test_dashboard_no_cost_breakdown(self, client):
        resp = client.get("/dashboard")
        assert "Cost Breakdown" not in resp.text

    def test_dashboard_has_theme_switcher(self, client):
        resp = client.get("/dashboard")
        assert "themeMenu" in resp.text
        assert "setTheme" in resp.text

    def test_dashboard_has_github_button(self, client):
        resp = client.get("/dashboard")
        assert "github-btn" in resp.text

    def test_dashboard_has_crypto_news(self, client):
        resp = client.get("/dashboard")
        assert "Crypto News" in resp.text
        assert "cryptoNewsPosts" in resp.text

    def test_dashboard_has_config_js_tag(self, client):
        resp = client.get("/dashboard")
        assert "config.js" in resp.text

    def test_dashboard_has_wallet_management_widget(self, client):
        resp = client.get("/dashboard")
        assert "w-wallet-mgmt" in resp.text
        assert "Wallet Management" in resp.text

    def test_dashboard_has_wallet_balance_widget(self, client):
        resp = client.get("/dashboard")
        assert "w-balances" in resp.text
        assert "Wallet Balances" in resp.text


# ── Static Assets ────────────────────────────────────────────────────────────

class TestStaticAssets:
    def test_themes_css_returns_200(self, client):
        resp = client.get("/static/themes.css")
        assert resp.status_code == 200
        assert "text/css" in resp.headers["content-type"]

    def test_themes_css_has_all_themes(self, client):
        resp = client.get("/static/themes.css")
        for theme in ["midnight", "slate", "ocean", "sand", "cloud",
                       "mint", "carbon", "graphite", "ember", "sakura"]:
            assert f'data-theme="{theme}"' in resp.text

    def test_theme_loader_js_returns_200(self, client):
        resp = client.get("/static/theme-loader.js")
        assert resp.status_code == 200
        assert "javascript" in resp.headers["content-type"]

    def test_theme_loader_js_reads_localstorage(self, client):
        resp = client.get("/static/theme-loader.js")
        assert "clawsafe-theme" in resp.text
        assert "localStorage" in resp.text

    def test_logo_returns_200(self, client):
        resp = client.get("/dashboard/logo.png")
        assert resp.status_code == 200
        assert "image/png" in resp.headers["content-type"]

    def test_dashboard_css_returns_200(self, client):
        resp = client.get("/static/dashboard.css")
        assert resp.status_code == 200
        assert "text/css" in resp.headers["content-type"]

    def test_pages_css_returns_200(self, client):
        resp = client.get("/static/pages.css")
        assert resp.status_code == 200
        assert "text/css" in resp.headers["content-type"]


# ── API Users Dashboard ─────────────────────────────────────────────────────

class TestApiUsersDashboard:
    def test_api_users_page_returns_200(self, client):
        resp = client.get("/dashboard/api-users")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]


# ── Feed Proxy Endpoints ─────────────────────────────────────────────────────

class TestFeedProxyEndpoints:
    """Proxy endpoints that were moved from publisher_service to frontend."""

    def test_crypto_prices_returns_200(self, client):
        resp = client.get("/crypto-prices")
        assert resp.status_code == 200

    def test_crypto_news_returns_200(self, client):
        resp = client.get("/crypto-news")
        assert resp.status_code == 200

    def test_moltbook_feed_returns_200(self, client):
        resp = client.get("/moltbook-feed")
        assert resp.status_code == 200

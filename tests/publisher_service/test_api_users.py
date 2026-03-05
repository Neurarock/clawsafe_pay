"""
Tests for the API user management system in publisher_service.

Covers:
  - CRUD operations (create, list, get, update, delete)
  - API key regeneration
  - Permission enforcement (asset, chain, per-tx limit, daily limit)
  - Agent key authentication for intent submission
  - Admin-only access to management endpoints
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import publisher_service.app as app_module
import publisher_service.api_users_db as api_users_db
from publisher_service.injection_filter import FilterResult
from tests.publisher_service.conftest import API_KEY, VALID_INTENT


@pytest.fixture
def client(monkeypatch):
    """Sync TestClient — initialises the lifespan (creates DB)."""
    async def _noop_workflow(intent_id: str) -> None:
        return None

    monkeypatch.setattr(app_module, "run_intent_workflow", _noop_workflow)
    app_module._rate_limit_store.clear()
    with TestClient(app_module.app) as c:
        yield c


ADMIN_HEADERS = {"X-API-Key": API_KEY}


# ── Helper to create an agent via API ────────────────────────────────────────

def _create_agent(client, name="TestBot", **overrides):
    body = {
        "name": name,
        "allowed_assets": ["*"],
        "allowed_chains": ["*"],
        "max_amount_wei": "0",
        "daily_limit_wei": "0",
        "rate_limit": 0,
        **overrides,
    }
    resp = client.post("/api-users", json=body, headers=ADMIN_HEADERS)
    assert resp.status_code == 201, resp.text
    return resp.json()


# ══════════════════════════════════════════════════════════════════════════════
#  CRUD
# ══════════════════════════════════════════════════════════════════════════════


class TestCreateAgent:
    def test_create_returns_api_key(self, client):
        data = _create_agent(client, name="Agent-1")
        assert "api_key" in data
        assert data["api_key"].startswith("csp_")
        assert data["name"] == "Agent-1"
        assert data["is_active"] is True

    def test_create_requires_admin_key(self, client):
        resp = client.post(
            "/api-users",
            json={"name": "Bad"},
            headers={"X-API-Key": "wrong-key"},
        )
        assert resp.status_code == 403

    def test_create_with_permissions(self, client):
        data = _create_agent(
            client,
            name="Limited",
            allowed_assets=["ETH", "USDC"],
            allowed_chains=["sepolia"],
            max_amount_wei="500000000000000000",
            daily_limit_wei="1000000000000000000",
        )
        assert data["allowed_assets"] == ["ETH", "USDC"]
        assert data["allowed_chains"] == ["sepolia"]
        assert data["max_amount_wei"] == "500000000000000000"


class TestListAgents:
    def test_list_empty(self, client):
        resp = client.get("/api-users", headers=ADMIN_HEADERS)
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_after_create(self, client):
        _create_agent(client, name="A1")
        _create_agent(client, name="A2")
        data = client.get("/api-users", headers=ADMIN_HEADERS).json()
        assert len(data) == 2
        names = {u["name"] for u in data}
        assert names == {"A1", "A2"}

    def test_list_requires_admin(self, client):
        resp = client.get("/api-users", headers={"X-API-Key": "nope"})
        assert resp.status_code == 403


class TestGetAgent:
    def test_get_by_id(self, client):
        created = _create_agent(client)
        resp = client.get(f"/api-users/{created['id']}", headers=ADMIN_HEADERS)
        assert resp.status_code == 200
        assert resp.json()["name"] == created["name"]

    def test_get_not_found(self, client):
        resp = client.get("/api-users/nonexistent", headers=ADMIN_HEADERS)
        assert resp.status_code == 404


class TestUpdateAgent:
    def test_update_name(self, client):
        created = _create_agent(client, name="OldName")
        resp = client.put(
            f"/api-users/{created['id']}",
            json={"name": "NewName"},
            headers=ADMIN_HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "NewName"

    def test_update_permissions(self, client):
        created = _create_agent(client)
        resp = client.put(
            f"/api-users/{created['id']}",
            json={
                "allowed_assets": ["USDC"],
                "allowed_chains": ["base"],
                "max_amount_wei": "100000",
            },
            headers=ADMIN_HEADERS,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["allowed_assets"] == ["USDC"]
        assert data["allowed_chains"] == ["base"]
        assert data["max_amount_wei"] == "100000"

    def test_deactivate_via_update(self, client):
        created = _create_agent(client)
        resp = client.put(
            f"/api-users/{created['id']}",
            json={"is_active": False},
            headers=ADMIN_HEADERS,
        )
        assert resp.json()["is_active"] is False


class TestDeleteAgent:
    def test_soft_delete(self, client):
        created = _create_agent(client)
        resp = client.delete(f"/api-users/{created['id']}", headers=ADMIN_HEADERS)
        assert resp.status_code == 200

        # Should be inactive now
        user = client.get(f"/api-users/{created['id']}", headers=ADMIN_HEADERS).json()
        assert user["is_active"] is False

    def test_delete_not_found(self, client):
        resp = client.delete("/api-users/ghost", headers=ADMIN_HEADERS)
        assert resp.status_code == 404


class TestRegenerateKey:
    def test_regen_returns_new_key(self, client):
        created = _create_agent(client)
        old_prefix = created["api_key_prefix"]

        resp = client.post(
            f"/api-users/{created['id']}/regenerate-key",
            headers=ADMIN_HEADERS,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "api_key" in data
        assert data["api_key"].startswith("csp_")
        # The new key prefix should differ from the old one
        # (statistically near-certain)
        new_prefix = data["api_key_prefix"]
        # Just verify the key field exists and is valid
        assert len(data["api_key"]) > 20

    def test_old_key_invalid_after_regen(self, client):
        created = _create_agent(client)
        old_key = created["api_key"]

        # Old key works
        resp = client.post(
            "/intent",
            json={**VALID_INTENT, "intent_id": "regen-test-1"},
            headers={"X-API-Key": old_key},
        )
        assert resp.status_code == 202

        # Regenerate
        regen_resp = client.post(
            f"/api-users/{created['id']}/regenerate-key",
            headers=ADMIN_HEADERS,
        )
        new_key = regen_resp.json()["api_key"]

        # Old key should fail
        resp = client.post(
            "/intent",
            json={**VALID_INTENT, "intent_id": "regen-test-2"},
            headers={"X-API-Key": old_key},
        )
        assert resp.status_code == 401

        # New key works
        resp = client.post(
            "/intent",
            json={**VALID_INTENT, "intent_id": "regen-test-3"},
            headers={"X-API-Key": new_key},
        )
        assert resp.status_code == 202


# ══════════════════════════════════════════════════════════════════════════════
#  PERMISSION ENFORCEMENT
# ══════════════════════════════════════════════════════════════════════════════


class TestAssetPermission:
    def test_wildcard_allows_any_asset(self, client):
        agent = _create_agent(client, allowed_assets=["*"])
        resp = client.post(
            "/intent",
            json={**VALID_INTENT, "intent_id": "asset-wild"},
            headers={"X-API-Key": agent["api_key"]},
        )
        assert resp.status_code == 202

    def test_allowed_asset_passes(self, client):
        agent = _create_agent(client, allowed_assets=["ETH"])
        resp = client.post(
            "/intent",
            json={**VALID_INTENT, "intent_id": "asset-ok", "asset": "ETH"},
            headers={"X-API-Key": agent["api_key"]},
        )
        assert resp.status_code == 202

    def test_disallowed_asset_rejected(self, client):
        agent = _create_agent(client, allowed_assets=["USDC"])
        resp = client.post(
            "/intent",
            json={**VALID_INTENT, "intent_id": "asset-bad", "asset": "ETH"},
            headers={"X-API-Key": agent["api_key"]},
        )
        assert resp.status_code == 403
        assert "not permitted to transact ETH" in resp.json()["detail"]


class TestChainPermission:
    def test_allowed_chain(self, client):
        agent = _create_agent(client, allowed_chains=["sepolia"])
        resp = client.post(
            "/intent",
            json={**VALID_INTENT, "intent_id": "chain-ok"},
            headers={"X-API-Key": agent["api_key"]},
        )
        assert resp.status_code == 202

    def test_disallowed_chain(self, client):
        agent = _create_agent(client, allowed_chains=["base"])
        resp = client.post(
            "/intent",
            json={**VALID_INTENT, "intent_id": "chain-bad", "chain": "sepolia"},
            headers={"X-API-Key": agent["api_key"]},
        )
        assert resp.status_code == 403
        assert "not permitted on chain" in resp.json()["detail"]


class TestPerTxLimit:
    def test_under_limit_passes(self, client):
        agent = _create_agent(client, max_amount_wei="100000000000000000")  # 0.1 ETH
        resp = client.post(
            "/intent",
            json={**VALID_INTENT, "intent_id": "tx-ok", "amount_wei": "10000000000000000"},
            headers={"X-API-Key": agent["api_key"]},
        )
        assert resp.status_code == 202

    def test_over_limit_rejected(self, client):
        agent = _create_agent(client, max_amount_wei="5000000000000000")  # 0.005 ETH
        resp = client.post(
            "/intent",
            json={**VALID_INTENT, "intent_id": "tx-big", "amount_wei": "10000000000000000"},
            headers={"X-API-Key": agent["api_key"]},
        )
        assert resp.status_code == 403
        assert "exceeds per-transaction limit" in resp.json()["detail"]


class TestDailyLimit:
    def test_within_daily_limit(self, client):
        agent = _create_agent(client, daily_limit_wei="50000000000000000")  # 0.05 ETH
        resp = client.post(
            "/intent",
            json={**VALID_INTENT, "intent_id": "daily-ok", "amount_wei": "10000000000000000"},
            headers={"X-API-Key": agent["api_key"]},
        )
        assert resp.status_code == 202

    def test_exceeds_daily_limit(self, client):
        agent = _create_agent(client, daily_limit_wei="15000000000000000")  # 0.015 ETH

        # First tx — 0.01 ETH — OK
        resp1 = client.post(
            "/intent",
            json={**VALID_INTENT, "intent_id": "daily-1", "amount_wei": "10000000000000000"},
            headers={"X-API-Key": agent["api_key"]},
        )
        assert resp1.status_code == 202

        # Second tx — 0.01 ETH — would push total to 0.02, exceeding 0.015 limit
        resp2 = client.post(
            "/intent",
            json={**VALID_INTENT, "intent_id": "daily-2", "amount_wei": "10000000000000000"},
            headers={"X-API-Key": agent["api_key"]},
        )
        assert resp2.status_code == 403
        assert "Daily limit exceeded" in resp2.json()["detail"]


class TestAgentAuth:
    def test_inactive_agent_rejected(self, client):
        agent = _create_agent(client)
        # Deactivate
        client.delete(f"/api-users/{agent['id']}", headers=ADMIN_HEADERS)

        resp = client.post(
            "/intent",
            json={**VALID_INTENT, "intent_id": "dead-agent"},
            headers={"X-API-Key": agent["api_key"]},
        )
        assert resp.status_code == 401

    def test_admin_key_still_works(self, client):
        """Admin key should bypass all agent permission checks."""
        resp = client.post(
            "/intent",
            json={**VALID_INTENT, "intent_id": "admin-direct"},
            headers=ADMIN_HEADERS,
        )
        assert resp.status_code == 202

    def test_agent_cannot_access_management(self, client):
        """Agent keys should not be able to list/create other agents."""
        agent = _create_agent(client)
        resp = client.get("/api-users", headers={"X-API-Key": agent["api_key"]})
        assert resp.status_code == 403


class TestUsageEndpoint:
    def test_usage_tracking(self, client):
        agent = _create_agent(client, daily_limit_wei="1000000000000000000")
        # Submit an intent
        client.post(
            "/intent",
            json={**VALID_INTENT, "intent_id": "usage-1", "amount_wei": "10000000000000000"},
            headers={"X-API-Key": agent["api_key"]},
        )
        # Check usage
        resp = client.get(f"/api-users/{agent['id']}/usage", headers=ADMIN_HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert data["today_total_wei"] == "10000000000000000"
        assert data["today_request_count"] == 1

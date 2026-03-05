"""
Tests for the wallet management system in publisher_service.

Covers:
  - CRUD operations (add, list, get, delete)
  - Set default wallet
  - Duplicate address prevention
  - Private key encryption/decryption
  - Wallet balance endpoint
  - Dashboard wallet widgets
  - Admin-only access enforcement
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch

import publisher_service.app as app_module
import publisher_service.wallets_db as wallets_db
from tests.publisher_service.conftest import API_KEY


@pytest.fixture(autouse=True)
def _patch_wallets_db(monkeypatch, patch_config):
    """Ensure wallets_db uses the same temp DB as everything else."""
    import publisher_service.config as config
    monkeypatch.setattr(wallets_db, "DATABASE_PATH", config.DATABASE_PATH)
    yield


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
SAMPLE_WALLET = {
    "address": "0xd8da6bf26964af9d7eed9e03e53415d37aa96045",
    "private_key": "0x4c0883a69102937d6231471b5dbb6204fe51296170827936ea5cce4ed6b20a01",
    "label": "Test Wallet",
    "chain": "sepolia",
}


def _add_wallet(client, **overrides):
    body = {**SAMPLE_WALLET, **overrides}
    resp = client.post("/wallets", json=body, headers=ADMIN_HEADERS)
    return resp


# ══════════════════════════════════════════════════════════════════════════════
#  ADD WALLET
# ══════════════════════════════════════════════════════════════════════════════


class TestAddWallet:
    def test_add_wallet_success(self, client):
        resp = _add_wallet(client)
        assert resp.status_code == 201
        data = resp.json()
        assert data["address"] == SAMPLE_WALLET["address"]
        assert data["label"] == "Test Wallet"
        assert data["chain"] == "sepolia"
        assert "private_key" not in data  # Never exposed
        assert "encrypted_key" not in data

    def test_add_wallet_first_is_default(self, client):
        resp = _add_wallet(client)
        assert resp.status_code == 201
        assert resp.json()["is_default"] is True

    def test_add_wallet_second_is_not_default(self, client):
        _add_wallet(client)
        resp = _add_wallet(client, address="0x1234567890abcdef1234567890abcdef12345678")
        assert resp.status_code == 201
        assert resp.json()["is_default"] is False

    def test_add_wallet_duplicate_address(self, client):
        _add_wallet(client)
        resp = _add_wallet(client)
        assert resp.status_code == 409
        assert "already exists" in resp.json()["detail"]

    def test_add_wallet_requires_admin(self, client):
        resp = client.post(
            "/wallets",
            json=SAMPLE_WALLET,
            headers={"X-API-Key": "wrong-key"},
        )
        assert resp.status_code == 403

    def test_add_wallet_missing_fields(self, client):
        resp = client.post(
            "/wallets",
            json={"address": "0xabc"},
            headers=ADMIN_HEADERS,
        )
        assert resp.status_code == 422


# ══════════════════════════════════════════════════════════════════════════════
#  LIST WALLETS
# ══════════════════════════════════════════════════════════════════════════════


class TestListWallets:
    def test_list_managed_empty(self, client):
        resp = client.get("/wallets/managed", headers=ADMIN_HEADERS)
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_managed_returns_wallets(self, client):
        _add_wallet(client)
        _add_wallet(client, address="0x1234567890abcdef1234567890abcdef12345678", label="Second")
        resp = client.get("/wallets/managed", headers=ADMIN_HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        # No private keys in response
        for w in data:
            assert "private_key" not in w
            assert "encrypted_key" not in w

    def test_list_managed_requires_admin(self, client):
        resp = client.get("/wallets/managed", headers={"X-API-Key": "wrong"})
        assert resp.status_code == 403

    def test_list_wallets_merges_env_and_db(self, client, monkeypatch):
        """GET /wallets merges DB wallets with env-configured ones."""
        monkeypatch.setattr(
            "publisher_service.config.AVAILABLE_WALLETS",
            ["0xENV_ADDR_1"],
        )
        _add_wallet(client)
        resp = client.get("/wallets")
        assert resp.status_code == 200
        data = resp.json()
        addrs = [a.lower() for a in data["wallets"]]
        assert SAMPLE_WALLET["address"].lower() in addrs
        assert "0xenv_addr_1" in addrs


# ══════════════════════════════════════════════════════════════════════════════
#  DELETE WALLET
# ══════════════════════════════════════════════════════════════════════════════


class TestDeleteWallet:
    def test_delete_wallet_success(self, client):
        resp = _add_wallet(client)
        wallet_id = resp.json()["id"]
        del_resp = client.delete(f"/wallets/{wallet_id}", headers=ADMIN_HEADERS)
        assert del_resp.status_code == 200
        assert del_resp.json()["detail"] == "Wallet deleted"

        # Verify it's gone
        managed = client.get("/wallets/managed", headers=ADMIN_HEADERS).json()
        assert len(managed) == 0

    def test_delete_wallet_not_found(self, client):
        resp = client.delete("/wallets/nonexistent", headers=ADMIN_HEADERS)
        assert resp.status_code == 404

    def test_delete_default_promotes_next(self, client):
        """Deleting the default wallet promotes the next oldest."""
        resp1 = _add_wallet(client)
        _add_wallet(client, address="0x1234567890abcdef1234567890abcdef12345678", label="Second")
        wallet1_id = resp1.json()["id"]

        # Delete default
        client.delete(f"/wallets/{wallet1_id}", headers=ADMIN_HEADERS)

        managed = client.get("/wallets/managed", headers=ADMIN_HEADERS).json()
        assert len(managed) == 1
        assert managed[0]["is_default"] is True

    def test_delete_requires_admin(self, client):
        resp = _add_wallet(client)
        wallet_id = resp.json()["id"]
        del_resp = client.delete(
            f"/wallets/{wallet_id}",
            headers={"X-API-Key": "wrong"},
        )
        assert del_resp.status_code == 403


# ══════════════════════════════════════════════════════════════════════════════
#  SET DEFAULT
# ══════════════════════════════════════════════════════════════════════════════


class TestSetDefault:
    def test_set_default_success(self, client):
        _add_wallet(client)
        resp2 = _add_wallet(
            client,
            address="0x1234567890abcdef1234567890abcdef12345678",
            label="Second",
        )
        wallet2_id = resp2.json()["id"]

        set_resp = client.post(
            f"/wallets/{wallet2_id}/set-default",
            headers=ADMIN_HEADERS,
        )
        assert set_resp.status_code == 200
        assert set_resp.json()["is_default"] is True

        # Verify first is no longer default
        managed = client.get("/wallets/managed", headers=ADMIN_HEADERS).json()
        defaults = [w for w in managed if w["is_default"]]
        assert len(defaults) == 1
        assert defaults[0]["id"] == wallet2_id

    def test_set_default_not_found(self, client):
        resp = client.post("/wallets/nonexistent/set-default", headers=ADMIN_HEADERS)
        assert resp.status_code == 404


# ══════════════════════════════════════════════════════════════════════════════
#  PRIVATE KEY ENCRYPTION
# ══════════════════════════════════════════════════════════════════════════════


class TestPrivateKeyEncryption:
    def test_encrypt_decrypt_roundtrip(self):
        """Private key survives encrypt → decrypt cycle."""
        original = "0x4c0883a69102937d6231471b5dbb6204fe51296170827936ea5cce4ed6b20a01"
        encrypted = wallets_db._encrypt(original)
        assert encrypted != original  # Not plaintext
        assert wallets_db._decrypt(encrypted) == original

    def test_stored_key_retrievable(self, client):
        """After adding a wallet, the private key can be retrieved via DB."""
        _add_wallet(client)
        key = wallets_db.get_private_key(SAMPLE_WALLET["address"])
        assert key == SAMPLE_WALLET["private_key"]

    def test_private_key_not_in_api_response(self, client):
        """Ensure no API endpoint ever returns the private key."""
        _add_wallet(client)

        # Check list
        managed = client.get("/wallets/managed", headers=ADMIN_HEADERS).json()
        for w in managed:
            assert "private_key" not in w
            assert "encrypted_key" not in w

        # Check /wallets
        wallets = client.get("/wallets").json()
        assert "private_key" not in str(wallets)


# ══════════════════════════════════════════════════════════════════════════════
#  WALLET BALANCES
# ══════════════════════════════════════════════════════════════════════════════


class TestWalletBalances:
    def test_balances_endpoint_returns_list(self, client, monkeypatch):
        """Balance endpoint returns a list with one entry per wallet."""
        _add_wallet(client)
        monkeypatch.setattr(
            "publisher_service.config.AVAILABLE_WALLETS", []
        )

        # Mock the httpx call to avoid real RPC calls
        from unittest.mock import MagicMock

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "jsonrpc": "2.0",
            "result": "0xDE0B6B3A7640000",  # 1 ETH in hex
            "id": 1,
        }

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            resp = client.get("/wallets/balances")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["address"] == SAMPLE_WALLET["address"]
        assert data[0]["balance_wei"] == "1000000000000000000"
        assert data[0]["balance_display"] == "1.000000"
        assert data[0]["symbol"] == "ETH"

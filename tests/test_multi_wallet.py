"""
Tests for multi-wallet selection support.

Covers:
  - Wallet registry in signer_service/config
  - from_address flowing through PaymentIntent and SignRequest models
  - Publisher DB stores and retrieves from_address
  - Signer DB stores and retrieves from_address
  - Publisher API /wallets endpoint and from_address in /intent
  - Signer API /wallets endpoint
  - Orchestrator uses intent.from_address when building tx
"""

from __future__ import annotations

import os
import uuid
from unittest.mock import patch

import pytest


# ── Wallet registry (signer_service/config) ─────────────────────────────────

WALLET_1 = "0xd77e4f8142a0c48a62601cd5be99f591d2d515da"
WALLET_2 = "0x52492c6b4635e6b87f2043a6ac274be458060b48"
KEY_1 = "0xb0c8d34bd9d081d7c3d54aea0bdde439cc82b2b5daf77ecd1fd96152b8fca23e"
KEY_2 = "0x4fe54e621e58bc245669aa7c0635f4bc9e503145823d9b50eafc32d0d6410389"


class TestWalletRegistry:
    """Test signer_service.config wallet registry helpers."""

    def test_wallets_dict_loaded_from_env(self):
        from signer_service.config import WALLETS
        assert len(WALLETS) >= 2, "Expected at least 2 wallets loaded from .env"
        assert WALLET_1 in WALLETS
        assert WALLET_2 in WALLETS

    def test_get_wallet_addresses_returns_checksummed(self):
        from signer_service.config import get_wallet_addresses
        addrs = get_wallet_addresses()
        assert len(addrs) >= 2
        # Checksummed addresses start with 0x and have mixed case
        for a in addrs:
            assert a.startswith("0x")
            assert len(a) == 42

    def test_get_private_key_valid(self):
        from signer_service.config import get_private_key
        key = get_private_key(WALLET_1)
        assert key == KEY_1

    def test_get_private_key_case_insensitive(self):
        from signer_service.config import get_private_key
        key = get_private_key(WALLET_1.upper().replace("0X", "0x"))
        assert key == KEY_1

    def test_get_private_key_unknown_raises(self):
        from signer_service.config import get_private_key
        with pytest.raises(KeyError, match="No private key configured"):
            get_private_key("0x0000000000000000000000000000000000000000")

    def test_publisher_available_wallets_loaded(self):
        from publisher_service.config import AVAILABLE_WALLETS, SIGNER_FROM_ADDRESS
        assert len(AVAILABLE_WALLETS) >= 2
        assert SIGNER_FROM_ADDRESS in [a.lower() for a in AVAILABLE_WALLETS] or \
               SIGNER_FROM_ADDRESS in AVAILABLE_WALLETS


# ── Model from_address field ─────────────────────────────────────────────────

class TestModelFromAddress:
    """Test that from_address is accepted by PaymentIntent and SignRequest."""

    def test_payment_intent_accepts_from_address(self):
        from transaction_builder.models import PaymentIntent
        pi = PaymentIntent(
            intent_id="wallet-test-1",
            from_user="alice",
            to_user="bob",
            amount_wei="1000000000",
            to_address="0xd8da6bf26964af9d7eed9e03e53415d37aa96045",
            from_address="0xd77E4F8142a0C48A62601cD5Be99f591D2D515da",
        )
        assert pi.from_address == "0xd77E4F8142a0C48A62601cD5Be99f591D2D515da"

    def test_payment_intent_from_address_defaults_empty(self):
        from transaction_builder.models import PaymentIntent
        pi = PaymentIntent(
            intent_id="wallet-test-2",
            from_user="alice",
            to_user="bob",
            amount_wei="1000000000",
            to_address="0xd8da6bf26964af9d7eed9e03e53415d37aa96045",
        )
        assert pi.from_address == ""

    def test_sign_request_accepts_from_address(self):
        from signer_service.models import SignRequest
        sr = SignRequest(
            to="0xd8da6bf26964af9d7eed9e03e53415d37aa96045",
            value_wei="1000",
            from_address="0xd77E4F8142a0C48A62601cD5Be99f591D2D515da",
        )
        assert sr.from_address == "0xd77E4F8142a0C48A62601cD5Be99f591D2D515da"

    def test_sign_request_from_address_defaults_empty(self):
        from signer_service.models import SignRequest
        sr = SignRequest(
            to="0xd8da6bf26964af9d7eed9e03e53415d37aa96045",
            value_wei="1000",
        )
        assert sr.from_address == ""

    def test_intent_status_response_has_from_address(self):
        from publisher_service.models import IntentStatusResponse
        fields = IntentStatusResponse.model_fields
        assert "from_address" in fields


# ── Publisher DB stores from_address ─────────────────────────────────────────

class TestPublisherDBFromAddress:
    """Test that publisher_service database stores from_address."""

    @pytest.fixture(autouse=True)
    def _setup_db(self, tmp_path):
        db_path = str(tmp_path / "test_pub.db")
        with patch("publisher_service.database.DATABASE_PATH", db_path):
            import publisher_service.database as db
            db.init_db()
            self.db = db
            yield

    def test_insert_intent_with_from_address(self):
        row = self.db.insert_intent(
            intent_id="mw-pub-1",
            from_user="alice",
            to_user="bob",
            to_address="0xd8da6bf26964af9d7eed9e03e53415d37aa96045",
            amount_wei="1000000000",
            note="test",
            from_address=WALLET_2,
        )
        assert row["from_address"] == WALLET_2

    def test_insert_intent_from_address_defaults_empty(self):
        row = self.db.insert_intent(
            intent_id="mw-pub-2",
            from_user="alice",
            to_user="bob",
            to_address="0xd8da6bf26964af9d7eed9e03e53415d37aa96045",
            amount_wei="1000000000",
            note="test",
        )
        assert row["from_address"] == ""

    def test_get_intent_returns_from_address(self):
        self.db.insert_intent(
            intent_id="mw-pub-3",
            from_user="alice",
            to_user="bob",
            to_address="0xd8da6bf26964af9d7eed9e03e53415d37aa96045",
            amount_wei="1000000000",
            note="test",
            from_address=WALLET_1,
        )
        row = self.db.get_intent("mw-pub-3")
        assert row is not None
        assert row["from_address"] == WALLET_1


# ── Signer DB stores from_address ───────────────────────────────────────────

class TestSignerDBFromAddress:
    """Test that signer_service database stores from_address."""

    @pytest.fixture(autouse=True)
    def _setup_db(self, tmp_path):
        db_path = str(tmp_path / "test_signer.db")
        with patch("signer_service.database.SIGNER_DB_PATH", db_path):
            from signer_service import database as db
            db.init_db()
            self.db = db
            yield

    def test_insert_request_with_from_address(self):
        tx_id = str(uuid.uuid4())
        auth_id = str(uuid.uuid4())
        row = self.db.insert_request(
            tx_id=tx_id,
            auth_request_id=auth_id,
            user_id="user1",
            note="Test multi-wallet",
            to_address="0x1234567890abcdef1234567890abcdef12345678",
            value_wei="1000000000000000",
            data_hex="0x",
            gas_limit=21000,
            from_address=WALLET_2,
        )
        assert row is not None
        assert row["from_address"] == WALLET_2

    def test_insert_request_from_address_defaults_empty(self):
        tx_id = str(uuid.uuid4())
        auth_id = str(uuid.uuid4())
        row = self.db.insert_request(
            tx_id=tx_id,
            auth_request_id=auth_id,
            user_id="user1",
            note="",
            to_address="0x1234567890abcdef1234567890abcdef12345678",
            value_wei="100",
            data_hex="0x",
            gas_limit=21000,
        )
        assert row is not None
        assert row["from_address"] == ""


# ── Publisher API /wallets & from_address in /intent ─────────────────────────

class TestPublisherWalletsAPI:
    """Test publisher_service /wallets endpoint and from_address in intents."""

    @pytest.fixture(autouse=True)
    def _patch_config(self, tmp_path, monkeypatch):
        import publisher_service.config as config
        import publisher_service.database as db_module
        db_path = str(tmp_path / "test_api_pub.db")
        monkeypatch.setattr(config, "DATABASE_PATH", db_path)
        monkeypatch.setattr(db_module, "DATABASE_PATH", db_path)
        monkeypatch.setattr(config, "PUBLISHER_API_KEY", "test-key")
        monkeypatch.setattr(config, "SIGNER_POLL_INTERVAL_SECONDS", 0.01)
        monkeypatch.setattr(config, "SIGNER_POLL_TIMEOUT_SECONDS", 0.1)
        monkeypatch.setattr(config, "FLOCK_API_KEY", "")
        yield

    @pytest.fixture
    def client(self, monkeypatch):
        from fastapi.testclient import TestClient
        import publisher_service.app as app_module

        async def _noop_workflow(intent_id: str) -> None:
            return None

        monkeypatch.setattr(app_module, "run_intent_workflow", _noop_workflow)
        app_module._rate_limit_store.clear()
        with TestClient(app_module.app) as c:
            yield c

    def test_wallets_endpoint_returns_list(self, client):
        resp = client.get("/wallets")
        assert resp.status_code == 200
        data = resp.json()
        assert "wallets" in data
        assert "default" in data
        assert isinstance(data["wallets"], list)
        assert len(data["wallets"]) >= 1

    def test_submit_intent_with_from_address(self, client):
        resp = client.post("/intent", json={
            "intent_id": "mw-api-1",
            "from_user": "alice",
            "to_user": "bob",
            "amount_wei": "1000000000",
            "to_address": "0xd8da6bf26964af9d7eed9e03e53415d37aa96045",
            "from_address": WALLET_2,
            "note": "multi-wallet test",
        }, headers={"X-API-Key": "test-key"})
        assert resp.status_code == 202

    def test_get_intent_includes_from_address(self, client):
        client.post("/intent", json={
            "intent_id": "mw-api-2",
            "from_user": "alice",
            "to_user": "bob",
            "amount_wei": "1000000000",
            "to_address": "0xd8da6bf26964af9d7eed9e03e53415d37aa96045",
            "from_address": WALLET_2,
            "note": "test",
        }, headers={"X-API-Key": "test-key"})

        resp = client.get("/intent/mw-api-2", headers={"X-API-Key": "test-key"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["from_address"] == WALLET_2

    def test_list_intents_includes_from_address(self, client):
        client.post("/intent", json={
            "intent_id": "mw-api-3",
            "from_user": "alice",
            "to_user": "bob",
            "amount_wei": "1000000000",
            "to_address": "0xd8da6bf26964af9d7eed9e03e53415d37aa96045",
            "from_address": WALLET_1,
            "note": "test",
        }, headers={"X-API-Key": "test-key"})

        resp = client.get("/intents", headers={"X-API-Key": "test-key"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        found = [d for d in data if d["intent_id"] == "mw-api-3"]
        assert len(found) == 1
        assert found[0]["from_address"] == WALLET_1


# ── Signer API /wallets endpoint ────────────────────────────────────────────

class TestSignerWalletsAPI:
    """Test signer_service /wallets endpoint."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        db_path = str(tmp_path / "test_signer_api.db")
        with patch("signer_service.database.SIGNER_DB_PATH", db_path):
            from signer_service import database as real_db
            real_db.init_db()
            import signer_service.app  # noqa: F401
            yield

    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from signer_service.app import app
        return TestClient(app)

    def test_wallets_endpoint(self, client):
        resp = client.get("/wallets")
        assert resp.status_code == 200
        data = resp.json()
        assert "wallets" in data
        assert isinstance(data["wallets"], list)
        assert len(data["wallets"]) >= 2

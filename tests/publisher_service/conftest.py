"""
Shared fixtures for publisher_service tests.
"""
from __future__ import annotations

import os
import pytest
import publisher_service.config as config

VALID_INTENT = {
    "intent_id": "test-intent-001",
    "from_user": "userA",
    "to_user": "userB",
    "chain": "sepolia",
    "asset": "ETH",
    "amount_wei": "10000000000000000",
    "to_address": "0xd8da6bf26964af9d7eed9e03e53415d37aa96045",
    "note": "lunch",
}

API_KEY = "test-api-key-12345"


@pytest.fixture(autouse=True)
def patch_config(tmp_path, monkeypatch):
    """Redirect DB to a temp file and set a deterministic API key."""
    db_path = str(tmp_path / "test_intents.db")
    monkeypatch.setattr(config, "DATABASE_PATH", db_path)
    monkeypatch.setattr(config, "PUBLISHER_API_KEY", API_KEY)
    # Prevent auto-seeding of default API user in tests
    monkeypatch.setattr(config, "DEFAULT_PUBLISHER_API", "")
    # Speed up signer polling in tests
    monkeypatch.setattr(config, "SIGNER_POLL_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(config, "SIGNER_POLL_TIMEOUT_SECONDS", 0.1)
    # Disable the Flock injection filter for unit tests — no real API calls
    monkeypatch.setattr(config, "FLOCK_API_KEY", "")
    # Re-patch the database module's imported constant too
    import publisher_service.database as db_module
    monkeypatch.setattr(db_module, "DATABASE_PATH", db_path)
    # Also patch api_users_db to use the same temp DB
    import publisher_service.api_users_db as api_users_db_module
    monkeypatch.setattr(api_users_db_module, "DATABASE_PATH", db_path)
    yield

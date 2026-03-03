"""
FastAPI endpoint tests for publisher_service.
Uses httpx.AsyncClient with the FastAPI app directly.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import publisher_service.app as app_module
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


# ── Health ───────────────────────────────────────────────────────────────────

def test_health_no_auth(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


# ── POST /intent — auth ───────────────────────────────────────────────────────

def test_submit_intent_missing_api_key(client):
    resp = client.post("/intent", json=VALID_INTENT)
    assert resp.status_code == 422  # Header(...) makes it required → validation error


def test_submit_intent_wrong_api_key(client):
    resp = client.post("/intent", json=VALID_INTENT, headers={"X-API-Key": "wrong"})
    assert resp.status_code == 401


# ── POST /intent — success ────────────────────────────────────────────────────

def test_submit_intent_returns_202(client):
    resp = client.post("/intent", json=VALID_INTENT, headers={"X-API-Key": API_KEY})
    assert resp.status_code == 202
    data = resp.json()
    assert data["intent_id"] == VALID_INTENT["intent_id"]
    assert data["status"] == "pending"


# ── POST /intent — duplicate ──────────────────────────────────────────────────

def test_submit_intent_duplicate_returns_409(client):
    headers = {"X-API-Key": API_KEY}
    client.post("/intent", json=VALID_INTENT, headers=headers)
    resp = client.post("/intent", json=VALID_INTENT, headers=headers)
    assert resp.status_code == 409


# ── POST /intent — invalid address ───────────────────────────────────────────

def test_submit_intent_invalid_address_returns_422(client):
    bad = {**VALID_INTENT, "intent_id": "test-bad-addr", "to_address": "not-an-address"}
    resp = client.post("/intent", json=bad, headers={"X-API-Key": API_KEY})
    assert resp.status_code == 422


# ── GET /intent/{id} ─────────────────────────────────────────────────────────

def test_get_intent_not_found_returns_404(client):
    resp = client.get("/intent/does-not-exist", headers={"X-API-Key": API_KEY})
    assert resp.status_code == 404


def test_get_intent_returns_current_status(client):
    headers = {"X-API-Key": API_KEY}
    client.post("/intent", json=VALID_INTENT, headers=headers)
    resp = client.get(f"/intent/{VALID_INTENT['intent_id']}", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["intent_id"] == VALID_INTENT["intent_id"]
    assert data["status"] in (
        "pending", "building", "reviewing", "awaiting_approval",
        "signing", "broadcast", "confirmed",
        "rejected", "expired", "blocked", "failed",
    )


def test_submit_intent_injection_score_at_block_threshold_rejected(client, monkeypatch):
    async def _high_score_filter(**kwargs):
        return FilterResult(score=8, reason="explicit prompt override", model_used="test-model")

    monkeypatch.setattr(app_module, "check_injection", _high_score_filter)
    resp = client.post("/intent", json={**VALID_INTENT, "intent_id": "test-inj-block"}, headers={"X-API-Key": API_KEY})
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert detail["error"] == "injection_detected"
    assert detail["score"] == 8


def test_submit_intent_warn_band_allows_request(client, monkeypatch):
    async def _warn_score_filter(**kwargs):
        return FilterResult(score=6, reason="suspicious phrasing", model_used="test-model")

    monkeypatch.setattr(app_module, "check_injection", _warn_score_filter)
    resp = client.post("/intent", json={**VALID_INTENT, "intent_id": "test-inj-warn"}, headers={"X-API-Key": API_KEY})
    assert resp.status_code == 202

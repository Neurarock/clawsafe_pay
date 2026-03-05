"""
Tests for reviewer_service.

- test_api.py-style tests for the FastAPI endpoints
- LLM client tests with mocked httpx (via respx)
- Heuristic fallback tests
"""
from __future__ import annotations

import json
import pytest
import respx
import httpx
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient

from reviewer_service.app import app
from reviewer_service.llm_client import (
    _heuristic_review,
    _parse_llm_response,
    review_transaction,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────

FAKE_DIGEST = "0x" + "ab" * 32
INTENT_ID = "review-test-001"

DRAFT_TX = {
    "intent_id": INTENT_ID,
    "chain_id": 11155111,
    "from_address": "0x742d35cc6634c0532925a3b8d4c9d5a3aa5a3eb",
    "to": "0xd8da6bf26964af9d7eed9e03e53415d37aa96045",
    "value_wei": "10000000000000000",
    "nonce": 5,
    "gas_limit": 21000,
    "max_fee_per_gas": "21500000000",
    "max_priority_fee_per_gas": "1500000000",
    "digest": FAKE_DIGEST,
    "data": "0x",
}

BASE_FEE = 10_000_000_000  # 10 gwei

GOOD_LLM_JSON = json.dumps({
    "verdict": "OK",
    "reasons": [],
    "summary": "Transaction looks normal.",
    "gas_assessment": {
        "estimated_total_fee_wei": str(21000 * 21_500_000_000),
        "is_reasonable": True,
        "reference": "max_fee is within normal range",
    },
})

client = TestClient(app)


# ── Endpoint tests ────────────────────────────────────────────────────────────

@patch("reviewer_service.app.review_transaction", new_callable=AsyncMock)
def test_review_endpoint_returns_report(mock_review):
    mock_review.return_value = {
        "verdict": "OK",
        "reasons": [],
        "summary": "Transaction looks normal.",
        "gas_assessment": {
            "estimated_total_fee_wei": "451500000000000",
            "is_reasonable": True,
            "reference": "within normal range",
        },
        "model_used": "glm-5",
    }

    resp = client.post("/review", json={
        "intent_id": INTENT_ID,
        "draft_tx": DRAFT_TX,
        "current_base_fee_wei": BASE_FEE,
    })

    assert resp.status_code == 200
    body = resp.json()
    assert body["intent_id"] == INTENT_ID
    assert body["digest"] == FAKE_DIGEST
    assert body["verdict"] == "OK"
    assert body["model_used"] == "glm-5"
    mock_review.assert_called_once()


@patch("reviewer_service.app.review_transaction", new_callable=AsyncMock)
def test_review_endpoint_block_verdict(mock_review):
    mock_review.return_value = {
        "verdict": "BLOCK",
        "reasons": ["gas manipulation"],
        "summary": "Blocked: gas fee is 50x base fee.",
        "gas_assessment": {"estimated_total_fee_wei": "0", "is_reasonable": False, "reference": "anomalous"},
        "model_used": "glm-5",
    }

    resp = client.post("/review", json={
        "intent_id": INTENT_ID,
        "draft_tx": DRAFT_TX,
        "current_base_fee_wei": BASE_FEE,
    })

    assert resp.status_code == 200
    assert resp.json()["verdict"] == "BLOCK"


def test_health_endpoint():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_review_missing_fields_returns_422():
    # Missing required fields
    resp = client.post("/review", json={"intent_id": INTENT_ID})
    assert resp.status_code == 422


# ── Heuristic review tests ────────────────────────────────────────────────────

def test_heuristic_ok_when_fee_is_normal():
    draft = dict(DRAFT_TX, max_fee_per_gas="25000000000", gas_limit=21000)
    result = _heuristic_review(draft, current_base_fee_wei=10_000_000_000)
    assert result["verdict"] == "OK"
    assert result["gas_assessment"]["is_reasonable"] is True


def test_heuristic_warn_when_fee_is_elevated():
    # 4x base fee → WARN
    draft = dict(DRAFT_TX, max_fee_per_gas="40000000000", gas_limit=21000)
    result = _heuristic_review(draft, current_base_fee_wei=10_000_000_000)
    assert result["verdict"] == "WARN"


def test_heuristic_block_when_fee_is_extreme():
    # 11x base fee → BLOCK
    draft = dict(DRAFT_TX, max_fee_per_gas="110000000000", gas_limit=21000)
    result = _heuristic_review(draft, current_base_fee_wei=10_000_000_000)
    assert result["verdict"] == "BLOCK"
    assert result["gas_assessment"]["is_reasonable"] is False


def test_heuristic_ok_when_base_fee_zero():
    # If base fee is 0, no ratio check — should not crash
    result = _heuristic_review(DRAFT_TX, current_base_fee_wei=0)
    assert result["verdict"] == "OK"


# ── LLM response parser tests ─────────────────────────────────────────────────

def test_parse_valid_json_response():
    result = _parse_llm_response(GOOD_LLM_JSON, DRAFT_TX, BASE_FEE)
    assert result["verdict"] == "OK"
    assert result["summary"] == "Transaction looks normal."
    assert result["gas_assessment"]["is_reasonable"] is True


def test_parse_json_with_markdown_fence():
    fenced = f"```json\n{GOOD_LLM_JSON}\n```"
    result = _parse_llm_response(fenced, DRAFT_TX, BASE_FEE)
    assert result["verdict"] == "OK"


def test_parse_unknown_verdict_defaults_to_warn():
    bad = json.dumps({"verdict": "MAYBE", "reasons": [], "summary": "?", "gas_assessment": {}})
    result = _parse_llm_response(bad, DRAFT_TX, BASE_FEE)
    assert result["verdict"] == "WARN"


def test_parse_unparseable_falls_back_to_heuristic():
    result = _parse_llm_response("This is not JSON at all.", DRAFT_TX, BASE_FEE)
    # Should fall back to heuristic — verdict must be a valid value
    assert result["verdict"] in {"OK", "WARN", "BLOCK"}


def test_parse_block_verdict_preserved():
    block_json = json.dumps({
        "verdict": "BLOCK",
        "reasons": ["suspicious"],
        "summary": "Blocked.",
        "gas_assessment": {"estimated_total_fee_wei": "0", "is_reasonable": False, "reference": "bad"},
    })
    result = _parse_llm_response(block_json, DRAFT_TX, BASE_FEE)
    assert result["verdict"] == "BLOCK"


# ── LLM client integration tests (httpx mocked via respx) ────────────────────

@pytest.mark.asyncio
@respx.mock
async def test_review_transaction_ok_response():
    """Z.AI returns valid JSON → verdict forwarded correctly."""
    import reviewer_service.config as config

    respx.post(f"{config.ZAI_API_BASE}/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={"choices": [{"message": {"content": GOOD_LLM_JSON}}]},
        )
    )

    result = await review_transaction(INTENT_ID, DRAFT_TX, BASE_FEE)
    assert result["verdict"] == "OK"
    assert result["model_used"] == config.ZAI_MODEL


@pytest.mark.asyncio
@respx.mock
async def test_review_transaction_zai_500_falls_back_to_heuristic():
    """Z.AI 5xx → fallback heuristic, not an exception."""
    import reviewer_service.config as config

    respx.post(f"{config.ZAI_API_BASE}/chat/completions").mock(
        return_value=httpx.Response(500, text="Internal Server Error")
    )

    result = await review_transaction(INTENT_ID, DRAFT_TX, BASE_FEE)
    assert result["verdict"] in {"OK", "WARN", "BLOCK"}
    assert "fallback" in result["model_used"]


@pytest.mark.asyncio
@respx.mock
async def test_review_transaction_zai_network_error_falls_back():
    """Z.AI network error → fallback heuristic, not an exception."""
    import reviewer_service.config as config

    respx.post(f"{config.ZAI_API_BASE}/chat/completions").mock(
        side_effect=httpx.ConnectError("connection refused")
    )

    result = await review_transaction(INTENT_ID, DRAFT_TX, BASE_FEE)
    assert result["verdict"] in {"OK", "WARN", "BLOCK"}
    assert "fallback" in result["model_used"]


@pytest.mark.asyncio
@respx.mock
async def test_review_transaction_logs_model_name(caplog):
    """Model name and intent_id must appear in logs (hackathon proof)."""
    import reviewer_service.config as config
    import logging

    respx.post(f"{config.ZAI_API_BASE}/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={"choices": [{"message": {"content": GOOD_LLM_JSON}}]},
        )
    )

    with caplog.at_level(logging.INFO, logger="reviewer_service.llm_client"):
        await review_transaction(INTENT_ID, DRAFT_TX, BASE_FEE)

    log_text = " ".join(caplog.messages)
    assert config.ZAI_MODEL in log_text
    assert INTENT_ID in log_text

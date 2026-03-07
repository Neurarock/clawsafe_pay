"""
Tests for the dual-reviewer (Z.AI GLM + Flock kimi-k2.5) pipeline.

Covers:
  - _reconcile_verdicts(): all agreement/disagreement combinations
  - _review_transaction_flock(): HTTP success, 500 fallback, network error, no API key
  - review_transaction_dual(): parallel execution, reconciliation, both models in log
"""
from __future__ import annotations

import json
import logging
from unittest.mock import patch

import httpx
import pytest
import respx

from reviewer_service.llm_client import (
    _heuristic_review,
    _reconcile_verdicts,
    _review_transaction_flock,
    review_transaction_dual,
)

# ── Shared fixtures ────────────────────────────────────────────────────────────

INTENT_ID = "dual-test-001"
BASE_FEE = 10_000_000_000  # 10 gwei

DRAFT_TX = {
    "intent_id": INTENT_ID,
    "chain_id": 11155111,
    "from_address": "0x742d35cc6634c0532925a3b8d4c9d5a3aa5a3eb",
    "to": "0xd8da6bf26964af9d7eed9e03e53415d37aa96045",
    "value_wei": "10000000000000000",
    "nonce": 7,
    "gas_limit": 21000,
    "max_fee_per_gas": "21500000000",
    "max_priority_fee_per_gas": "1500000000",
    "digest": "0x" + "cd" * 32,
    "data": "0x",
}

FLOCK_URL = "https://api.flock.io/v1/chat/completions"


def _llm_ok_json(summary="Transaction is safe."):
    return json.dumps({
        "verdict": "OK",
        "reasons": [],
        "summary": summary,
        "gas_assessment": {
            "estimated_total_fee_wei": str(21000 * 21_500_000_000),
            "is_reasonable": True,
            "reference": "within normal range",
        },
    })


def _llm_warn_json(reason="elevated gas"):
    return json.dumps({
        "verdict": "WARN",
        "reasons": [reason],
        "summary": "Minor concern flagged.",
        "gas_assessment": {
            "estimated_total_fee_wei": str(21000 * 21_500_000_000),
            "is_reasonable": True,
            "reference": "slightly elevated",
        },
    })


def _llm_block_json(reason="gas manipulation"):
    return json.dumps({
        "verdict": "BLOCK",
        "reasons": [reason],
        "summary": "Transaction blocked.",
        "gas_assessment": {
            "estimated_total_fee_wei": "0",
            "is_reasonable": False,
            "reference": "anomalous",
        },
    })


def _result(verdict, model, reasons=None, summary="Summary."):
    return {
        "verdict": verdict,
        "reasons": reasons or [],
        "summary": summary,
        "gas_assessment": {"estimated_total_fee_wei": "100", "is_reasonable": True, "reference": "ok"},
        "model_used": model,
    }


# ── _reconcile_verdicts: agreement cases ──────────────────────────────────────

def test_reconcile_both_ok():
    result = _reconcile_verdicts(_result("OK", "glm-5"), _result("OK", "kimi-k2.5"))
    assert result["verdict"] == "OK"
    assert result["models_agreed"] is True
    assert result["individual_verdicts"] == {"zai": "OK", "flock": "OK"}


def test_reconcile_both_warn():
    result = _reconcile_verdicts(_result("WARN", "glm-5"), _result("WARN", "kimi-k2.5"))
    assert result["verdict"] == "WARN"
    assert result["models_agreed"] is True


def test_reconcile_both_block():
    result = _reconcile_verdicts(_result("BLOCK", "glm-5"), _result("BLOCK", "kimi-k2.5"))
    assert result["verdict"] == "BLOCK"
    assert result["models_agreed"] is True


# ── _reconcile_verdicts: disagreement → conservative verdict ──────────────────

def test_reconcile_zai_block_flock_ok():
    """ZAI=BLOCK beats Flock=OK — take BLOCK."""
    result = _reconcile_verdicts(_result("BLOCK", "glm-5"), _result("OK", "kimi-k2.5"))
    assert result["verdict"] == "BLOCK"
    assert result["models_agreed"] is False
    assert result["individual_verdicts"] == {"zai": "BLOCK", "flock": "OK"}


def test_reconcile_zai_ok_flock_block():
    """Flock=BLOCK beats ZAI=OK — take BLOCK."""
    result = _reconcile_verdicts(_result("OK", "glm-5"), _result("BLOCK", "kimi-k2.5"))
    assert result["verdict"] == "BLOCK"
    assert result["models_agreed"] is False


def test_reconcile_zai_warn_flock_ok():
    """ZAI=WARN beats Flock=OK — take WARN."""
    result = _reconcile_verdicts(_result("WARN", "glm-5"), _result("OK", "kimi-k2.5"))
    assert result["verdict"] == "WARN"
    assert result["models_agreed"] is False


def test_reconcile_zai_ok_flock_warn():
    """Flock=WARN beats ZAI=OK — take WARN."""
    result = _reconcile_verdicts(_result("OK", "glm-5"), _result("WARN", "kimi-k2.5"))
    assert result["verdict"] == "WARN"
    assert result["models_agreed"] is False


def test_reconcile_zai_block_flock_warn():
    """ZAI=BLOCK beats Flock=WARN — take BLOCK."""
    result = _reconcile_verdicts(_result("BLOCK", "glm-5"), _result("WARN", "kimi-k2.5"))
    assert result["verdict"] == "BLOCK"
    assert result["models_agreed"] is False


# ── _reconcile_verdicts: reason attribution ───────────────────────────────────

def test_reconcile_reasons_attributed_with_model_prefix():
    """Each reason is prefixed with [Z.AI/model] or [Flock/model]."""
    zai = _result("WARN", "glm-5", reasons=["elevated gas"])
    flock = _result("OK", "kimi-k2.5", reasons=[])
    result = _reconcile_verdicts(zai, flock)
    assert any("[Z.AI/glm-5]" in r for r in result["reasons"])


def test_reconcile_flock_reasons_attributed():
    zai = _result("OK", "glm-5", reasons=[])
    flock = _result("WARN", "kimi-k2.5", reasons=["suspicious recipient"])
    result = _reconcile_verdicts(zai, flock)
    assert any("[Flock/kimi-k2.5]" in r for r in result["reasons"])


def test_reconcile_disagreement_note_appended_to_reasons():
    """When models disagree, a disagreement note is added to reasons."""
    result = _reconcile_verdicts(_result("BLOCK", "glm-5"), _result("OK", "kimi-k2.5"))
    disagree_notes = [r for r in result["reasons"] if "disagreed" in r or "conservative" in r]
    assert len(disagree_notes) > 0


def test_reconcile_no_disagreement_note_when_agreed():
    """No disagreement note added when models agree."""
    result = _reconcile_verdicts(_result("OK", "glm-5"), _result("OK", "kimi-k2.5"))
    disagree_notes = [r for r in result["reasons"] if "disagreed" in r]
    assert len(disagree_notes) == 0


# ── _reconcile_verdicts: summary handling ─────────────────────────────────────

def test_reconcile_different_summaries_are_combined():
    zai = _result("OK", "glm-5", summary="ZAI summary.")
    flock = _result("OK", "kimi-k2.5", summary="Flock summary.")
    result = _reconcile_verdicts(zai, flock)
    assert "ZAI summary." in result["summary"]
    assert "Flock summary." in result["summary"]


def test_reconcile_identical_summaries_not_duplicated():
    same = "Transaction is fine."
    result = _reconcile_verdicts(_result("OK", "glm-5", summary=same), _result("OK", "kimi-k2.5", summary=same))
    # Summary should appear exactly once (not "Transaction is fine. | Transaction is fine.")
    assert result["summary"].count(same) == 1


# ── _reconcile_verdicts: model_used field ─────────────────────────────────────

def test_reconcile_model_used_contains_both_models():
    result = _reconcile_verdicts(_result("OK", "glm-5"), _result("OK", "kimi-k2.5"))
    assert "glm-5" in result["model_used"]
    assert "kimi-k2.5" in result["model_used"]


# ── _review_transaction_flock: HTTP success ───────────────────────────────────

@pytest.mark.asyncio
@respx.mock
async def test_flock_review_ok_response():
    """Flock returns valid OK JSON → verdict forwarded correctly."""
    respx.post(FLOCK_URL).mock(
        return_value=httpx.Response(
            200,
            json={"choices": [{"message": {"content": _llm_ok_json()}}]},
        )
    )
    with patch("reviewer_service.config.FLOCK_API_KEY", "test-flock-key"):
        result = await _review_transaction_flock(INTENT_ID, DRAFT_TX, BASE_FEE)
    assert result["verdict"] == "OK"


@pytest.mark.asyncio
@respx.mock
async def test_flock_review_warn_response():
    """Flock returns WARN → preserved correctly."""
    respx.post(FLOCK_URL).mock(
        return_value=httpx.Response(
            200,
            json={"choices": [{"message": {"content": _llm_warn_json()}}]},
        )
    )
    with patch("reviewer_service.config.FLOCK_API_KEY", "test-flock-key"):
        result = await _review_transaction_flock(INTENT_ID, DRAFT_TX, BASE_FEE)
    assert result["verdict"] == "WARN"


@pytest.mark.asyncio
@respx.mock
async def test_flock_review_block_response():
    """Flock returns BLOCK → preserved correctly."""
    respx.post(FLOCK_URL).mock(
        return_value=httpx.Response(
            200,
            json={"choices": [{"message": {"content": _llm_block_json()}}]},
        )
    )
    with patch("reviewer_service.config.FLOCK_API_KEY", "test-flock-key"):
        result = await _review_transaction_flock(INTENT_ID, DRAFT_TX, BASE_FEE)
    assert result["verdict"] == "BLOCK"


@pytest.mark.asyncio
@respx.mock
async def test_flock_review_model_used_is_kimi():
    """model_used reflects the configured Flock model name."""
    respx.post(FLOCK_URL).mock(
        return_value=httpx.Response(
            200,
            json={"choices": [{"message": {"content": _llm_ok_json()}}]},
        )
    )
    with patch("reviewer_service.config.FLOCK_API_KEY", "test-flock-key"), \
         patch("reviewer_service.config.FLOCK_REVIEW_MODEL", "kimi-k2.5"):
        result = await _review_transaction_flock(INTENT_ID, DRAFT_TX, BASE_FEE)
    assert result["model_used"] == "kimi-k2.5"


# ── _review_transaction_flock: fallback cases ─────────────────────────────────

@pytest.mark.asyncio
@respx.mock
async def test_flock_review_500_falls_back_to_heuristic():
    """Flock HTTP 500 → heuristic fallback, no exception raised."""
    respx.post(FLOCK_URL).mock(
        return_value=httpx.Response(500, text="Internal Server Error")
    )
    with patch("reviewer_service.config.FLOCK_API_KEY", "test-flock-key"):
        result = await _review_transaction_flock(INTENT_ID, DRAFT_TX, BASE_FEE)
    assert result["verdict"] in {"OK", "WARN", "BLOCK"}
    assert "fallback" in result["model_used"]


@pytest.mark.asyncio
@respx.mock
async def test_flock_review_network_error_falls_back():
    """Flock network error → heuristic fallback, no exception raised."""
    respx.post(FLOCK_URL).mock(side_effect=httpx.ConnectError("refused"))
    with patch("reviewer_service.config.FLOCK_API_KEY", "test-flock-key"):
        result = await _review_transaction_flock(INTENT_ID, DRAFT_TX, BASE_FEE)
    assert result["verdict"] in {"OK", "WARN", "BLOCK"}
    assert "fallback" in result["model_used"]


@pytest.mark.asyncio
async def test_flock_review_no_api_key_skips_gracefully():
    """No FLOCK_API_KEY → returns heuristic result with 'skipped' in model_used."""
    with patch("reviewer_service.config.FLOCK_API_KEY", ""):
        result = await _review_transaction_flock(INTENT_ID, DRAFT_TX, BASE_FEE)
    assert result["verdict"] in {"OK", "WARN", "BLOCK"}
    assert "skipped" in result["model_used"]


@pytest.mark.asyncio
@respx.mock
async def test_flock_review_logs_model_name_and_intent_id(caplog):
    """kimi-k2.5 and intent_id must appear in logs (hackathon proof)."""
    respx.post(FLOCK_URL).mock(
        return_value=httpx.Response(
            200,
            json={"choices": [{"message": {"content": _llm_ok_json()}}]},
        )
    )
    with patch("reviewer_service.config.FLOCK_API_KEY", "test-flock-key"), \
         patch("reviewer_service.config.FLOCK_REVIEW_MODEL", "kimi-k2.5"), \
         caplog.at_level(logging.INFO, logger="reviewer_service.llm_client"):
        await _review_transaction_flock(INTENT_ID, DRAFT_TX, BASE_FEE)

    log_text = " ".join(caplog.messages)
    assert "kimi-k2.5" in log_text
    assert INTENT_ID in log_text


# ── review_transaction_dual: orchestration ────────────────────────────────────

@pytest.mark.asyncio
@respx.mock
async def test_dual_review_both_agree_ok():
    """Both models return OK → final verdict OK, models_agreed=True."""
    import reviewer_service.config as cfg

    respx.post(f"{cfg.ZAI_API_BASE}/chat/completions").mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {"content": _llm_ok_json("ZAI ok.")}}]})
    )
    respx.post(FLOCK_URL).mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {"content": _llm_ok_json("Flock ok.")}}]})
    )

    with patch("reviewer_service.config.FLOCK_API_KEY", "test-flock-key"):
        result = await review_transaction_dual(INTENT_ID, DRAFT_TX, BASE_FEE)

    assert result["verdict"] == "OK"
    assert result["models_agreed"] is True
    assert result["individual_verdicts"]["zai"] == "OK"
    assert result["individual_verdicts"]["flock"] == "OK"


@pytest.mark.asyncio
@respx.mock
async def test_dual_review_disagreement_takes_conservative():
    """ZAI=OK, Flock=WARN → final verdict is WARN (conservative), agreed=False."""
    import reviewer_service.config as cfg

    respx.post(f"{cfg.ZAI_API_BASE}/chat/completions").mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {"content": _llm_ok_json()}}]})
    )
    respx.post(FLOCK_URL).mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {"content": _llm_warn_json()}}]})
    )

    with patch("reviewer_service.config.FLOCK_API_KEY", "test-flock-key"):
        result = await review_transaction_dual(INTENT_ID, DRAFT_TX, BASE_FEE)

    assert result["verdict"] == "WARN"
    assert result["models_agreed"] is False
    assert result["individual_verdicts"]["zai"] == "OK"
    assert result["individual_verdicts"]["flock"] == "WARN"


@pytest.mark.asyncio
@respx.mock
async def test_dual_review_flock_block_overrides_zai_ok():
    """ZAI=OK, Flock=BLOCK → final verdict BLOCK (most conservative)."""
    import reviewer_service.config as cfg

    respx.post(f"{cfg.ZAI_API_BASE}/chat/completions").mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {"content": _llm_ok_json()}}]})
    )
    respx.post(FLOCK_URL).mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {"content": _llm_block_json()}}]})
    )

    with patch("reviewer_service.config.FLOCK_API_KEY", "test-flock-key"):
        result = await review_transaction_dual(INTENT_ID, DRAFT_TX, BASE_FEE)

    assert result["verdict"] == "BLOCK"
    assert result["models_agreed"] is False


@pytest.mark.asyncio
@respx.mock
async def test_dual_review_flock_failure_degrades_gracefully():
    """Flock 500 → heuristic fallback; dual review still completes and returns a result."""
    import reviewer_service.config as cfg

    respx.post(f"{cfg.ZAI_API_BASE}/chat/completions").mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {"content": _llm_ok_json()}}]})
    )
    respx.post(FLOCK_URL).mock(return_value=httpx.Response(500, text="err"))

    with patch("reviewer_service.config.FLOCK_API_KEY", "test-flock-key"):
        result = await review_transaction_dual(INTENT_ID, DRAFT_TX, BASE_FEE)

    assert result["verdict"] in {"OK", "WARN", "BLOCK"}
    assert "individual_verdicts" in result


@pytest.mark.asyncio
@respx.mock
async def test_dual_review_model_used_contains_both_models():
    """model_used string should name both Z.AI and Flock models."""
    import reviewer_service.config as cfg

    respx.post(f"{cfg.ZAI_API_BASE}/chat/completions").mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {"content": _llm_ok_json()}}]})
    )
    respx.post(FLOCK_URL).mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {"content": _llm_ok_json()}}]})
    )

    with patch("reviewer_service.config.FLOCK_API_KEY", "test-flock-key"), \
         patch("reviewer_service.config.FLOCK_REVIEW_MODEL", "kimi-k2.5"), \
         patch("reviewer_service.config.ZAI_MODEL", "glm-5"):
        result = await review_transaction_dual(INTENT_ID, DRAFT_TX, BASE_FEE)

    assert "glm-5" in result["model_used"]
    assert "kimi-k2.5" in result["model_used"]


@pytest.mark.asyncio
@respx.mock
async def test_dual_review_both_block_unanimous():
    """Both say BLOCK → BLOCK, agreed=True, no disagreement note in reasons."""
    import reviewer_service.config as cfg

    respx.post(f"{cfg.ZAI_API_BASE}/chat/completions").mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {"content": _llm_block_json()}}]})
    )
    respx.post(FLOCK_URL).mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {"content": _llm_block_json()}}]})
    )

    with patch("reviewer_service.config.FLOCK_API_KEY", "test-flock-key"):
        result = await review_transaction_dual(INTENT_ID, DRAFT_TX, BASE_FEE)

    assert result["verdict"] == "BLOCK"
    assert result["models_agreed"] is True
    disagree_notes = [r for r in result["reasons"] if "disagreed" in r]
    assert len(disagree_notes) == 0


@pytest.mark.asyncio
@respx.mock
async def test_dual_review_reasons_carry_model_attribution():
    """Each reason in the combined output is prefixed with the source model."""
    import reviewer_service.config as cfg

    respx.post(f"{cfg.ZAI_API_BASE}/chat/completions").mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {"content": _llm_warn_json("zai reason")}}]})
    )
    respx.post(FLOCK_URL).mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {"content": _llm_warn_json("flock reason")}}]})
    )

    with patch("reviewer_service.config.FLOCK_API_KEY", "test-flock-key"):
        result = await review_transaction_dual(INTENT_ID, DRAFT_TX, BASE_FEE)

    reasons_text = " ".join(result["reasons"])
    assert "[Z.AI/" in reasons_text
    assert "[Flock/" in reasons_text


@pytest.mark.asyncio
@respx.mock
async def test_dual_review_disagreement_logged_as_warning(caplog):
    """When models disagree, a WARNING is emitted to the log."""
    import reviewer_service.config as cfg

    respx.post(f"{cfg.ZAI_API_BASE}/chat/completions").mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {"content": _llm_ok_json()}}]})
    )
    respx.post(FLOCK_URL).mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {"content": _llm_block_json()}}]})
    )

    with patch("reviewer_service.config.FLOCK_API_KEY", "test-flock-key"), \
         caplog.at_level(logging.WARNING, logger="reviewer_service.llm_client"):
        await review_transaction_dual(INTENT_ID, DRAFT_TX, BASE_FEE)

    assert any("DISAGREEMENT" in m or "disagreed" in m for m in caplog.messages)

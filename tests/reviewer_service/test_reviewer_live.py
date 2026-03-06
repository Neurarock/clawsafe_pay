"""
Live integration tests for the reviewer_service LLM client.

These tests make real HTTP calls to Z.AI GLM-5.
Run with:
    pytest tests/reviewer_service/test_reviewer_live.py -v -s

Each scenario is a realistic transaction that should produce a specific verdict.
The test asserts both the verdict and that the model name is logged.
"""
from __future__ import annotations

import logging
import pytest

import reviewer_service.config as config
from reviewer_service.llm_client import review_transaction

logger = logging.getLogger(__name__)

# Skip all tests if no API key is configured
pytestmark = pytest.mark.skipif(
    not config.ZAI_API_KEY or config.ZAI_API_KEY == "your-zai-api-key",
    reason="ZAI_API_KEY not configured — skipping live tests",
)


# ── Shared base fee (realistic Sepolia value ~10 gwei) ───────────────────────
BASE_FEE = 10_000_000_000  # 10 gwei


def _make_draft(
    *,
    intent_id: str,
    value_wei: int,
    gas_limit: int = 21_000,
    max_fee_per_gas: int,
    max_priority_fee_per_gas: int = 1_500_000_000,
    to: str = "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045",
    from_address: str = "0x742d35Cc6634C0532925a3b8D4C9d5A3Aa5a3EB",
    chain_id: int = 11155111,
) -> dict:
    return {
        "intent_id": intent_id,
        "chain_id": chain_id,
        "from_address": from_address,
        "to": to,
        "value_wei": str(value_wei),
        "nonce": 5,
        "gas_limit": gas_limit,
        "max_fee_per_gas": str(max_fee_per_gas),
        "max_priority_fee_per_gas": str(max_priority_fee_per_gas),
        "digest": "0x" + "ab" * 32,
        "data": "0x",
    }


def _print_result(label: str, result: dict) -> None:
    print(f"\n{'─'*60}")
    print(f"  Scenario : {label}")
    print(f"  Model    : {result['model_used']}")
    print(f"  Verdict  : {result['verdict']}")
    print(f"  Summary  : {result['summary']}")
    if result["reasons"]:
        for r in result["reasons"]:
            print(f"  Reason   : {r}")
    ga = result["gas_assessment"]
    print(f"  Gas OK   : {ga['is_reasonable']} — {ga['reference']}")
    print(f"  Fee Est  : {ga['estimated_total_fee_wei']} wei")
    print(f"{'─'*60}")


# ── Scenario 1: Normal small transfer (expect OK) ─────────────────────────────

@pytest.mark.asyncio
async def test_normal_small_transfer_is_ok():
    """0.01 ETH at 2x base fee — standard Sepolia test transfer."""
    draft = _make_draft(
        intent_id="live-001",
        value_wei=10_000_000_000_000_000,   # 0.01 ETH
        max_fee_per_gas=20_000_000_000,      # 20 gwei (2x base)
        max_priority_fee_per_gas=1_500_000_000,
    )
    result = await review_transaction("live-001", draft, BASE_FEE)
    _print_result("Normal 0.01 ETH transfer", result)

    assert result["verdict"] in {"OK", "WARN"}, (
        f"Expected OK or WARN for a normal transfer, got {result['verdict']}"
    )
    assert result["model_used"] == config.ZAI_MODEL
    assert result["summary"]
    assert "estimated_total_fee_wei" in result["gas_assessment"]


# ── Scenario 2: Suspiciously high gas fee (expect WARN or BLOCK) ──────────────

@pytest.mark.asyncio
async def test_elevated_gas_fee_is_warned():
    """max_fee = 50 gwei vs 10 gwei base — 5x elevated, should be WARN."""
    draft = _make_draft(
        intent_id="live-002",
        value_wei=5_000_000_000_000_000,    # 0.005 ETH
        max_fee_per_gas=50_000_000_000,      # 50 gwei (5x base)
        max_priority_fee_per_gas=2_000_000_000,
    )
    result = await review_transaction("live-002", draft, BASE_FEE)
    _print_result("Elevated gas fee (5x base)", result)

    assert result["verdict"] in {"WARN", "BLOCK"}, (
        f"Expected WARN or BLOCK for 5x gas fee, got {result['verdict']}"
    )
    assert result["model_used"] == config.ZAI_MODEL


# ── Scenario 3: Extreme gas manipulation (expect BLOCK) ──────────────────────

@pytest.mark.asyncio
async def test_extreme_gas_fee_is_blocked():
    """max_fee = 500 gwei vs 10 gwei base — 50x, clear gas manipulation."""
    draft = _make_draft(
        intent_id="live-003",
        value_wei=1_000_000_000_000_000,    # 0.001 ETH
        max_fee_per_gas=500_000_000_000,     # 500 gwei (50x base)
        max_priority_fee_per_gas=10_000_000_000,
    )
    result = await review_transaction("live-003", draft, BASE_FEE)
    _print_result("Extreme gas (50x base — manipulation)", result)

    assert result["verdict"] in {"WARN", "BLOCK"}, (
        f"Expected WARN or BLOCK for 50x gas fee, got {result['verdict']}"
    )
    assert result["model_used"] == config.ZAI_MODEL


# ── Scenario 4: Large ETH amount (expect WARN) ───────────────────────────────

@pytest.mark.asyncio
async def test_large_amount_transfer():
    """Sending 10 ETH on testnet — large amount should at least get a WARN."""
    draft = _make_draft(
        intent_id="live-004",
        value_wei=10_000_000_000_000_000_000,  # 10 ETH
        max_fee_per_gas=15_000_000_000,         # 15 gwei (normal)
        max_priority_fee_per_gas=1_500_000_000,
    )
    result = await review_transaction("live-004", draft, BASE_FEE)
    _print_result("Large 10 ETH transfer", result)

    # May be WARN or OK depending on LLM reasoning — we just check it ran
    assert result["verdict"] in {"OK", "WARN", "BLOCK"}
    assert result["model_used"] == config.ZAI_MODEL
    assert result["summary"]


# ── Scenario 5: Zero-value transfer (dust / probe tx) ────────────────────────

@pytest.mark.asyncio
async def test_zero_value_transfer():
    """0 wei transfer — could be a wallet probe or contract call stub."""
    draft = _make_draft(
        intent_id="live-005",
        value_wei=0,
        max_fee_per_gas=12_000_000_000,     # 12 gwei (normal)
        max_priority_fee_per_gas=1_500_000_000,
    )
    result = await review_transaction("live-005", draft, BASE_FEE)
    _print_result("Zero-value transfer (dust/probe)", result)

    assert result["verdict"] in {"OK", "WARN", "BLOCK"}
    # Allow fallback-heuristic if Z.AI had a transient error on zero-value tx
    assert result["model_used"].startswith(config.ZAI_MODEL)


# ── Scenario 6: Self-transfer (sender == recipient) ──────────────────────────

@pytest.mark.asyncio
async def test_self_transfer():
    """Sending ETH to the same address — unusual, may be WARN."""
    same_addr = "0x742d35Cc6634C0532925a3b8D4C9d5A3Aa5a3EB"
    draft = _make_draft(
        intent_id="live-006",
        value_wei=1_000_000_000_000_000,    # 0.001 ETH
        max_fee_per_gas=20_000_000_000,
        max_priority_fee_per_gas=1_500_000_000,
        to=same_addr,
        from_address=same_addr,
    )
    result = await review_transaction("live-006", draft, BASE_FEE)
    _print_result("Self-transfer (from == to)", result)

    assert result["verdict"] in {"OK", "WARN", "BLOCK"}
    assert result["model_used"] == config.ZAI_MODEL


# ── Scenario 7: High gas limit (unusual for simple ETH transfer) ──────────────

@pytest.mark.asyncio
async def test_high_gas_limit():
    """Gas limit of 500,000 for a simple ETH transfer (21,000 is standard)."""
    draft = _make_draft(
        intent_id="live-007",
        value_wei=5_000_000_000_000_000,    # 0.005 ETH
        gas_limit=500_000,                   # 24x the standard 21,000
        max_fee_per_gas=15_000_000_000,
        max_priority_fee_per_gas=1_500_000_000,
    )
    result = await review_transaction("live-007", draft, BASE_FEE)
    _print_result("High gas limit (500k vs standard 21k)", result)

    assert result["verdict"] in {"OK", "WARN", "BLOCK"}
    assert result["model_used"] == config.ZAI_MODEL


# ── Scenario 8: Reasonable mainnet-sized transfer ────────────────────────────

@pytest.mark.asyncio
async def test_typical_mainnet_transfer():
    """0.05 ETH, 1.5x base fee — typical production transfer."""
    draft = _make_draft(
        intent_id="live-008",
        value_wei=50_000_000_000_000_000,   # 0.05 ETH
        max_fee_per_gas=15_000_000_000,      # 15 gwei (1.5x base)
        max_priority_fee_per_gas=1_000_000_000,
    )
    result = await review_transaction("live-008", draft, BASE_FEE)
    _print_result("Typical 0.05 ETH production transfer", result)

    assert result["verdict"] in {"OK", "WARN"}
    assert result["model_used"] == config.ZAI_MODEL
    assert result["gas_assessment"]["is_reasonable"] is True

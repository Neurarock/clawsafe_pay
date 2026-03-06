"""
Z.AI / GLM-5 HTTP client for the reviewer_service.

Sends a transaction review prompt to the Z.AI chat completions API and
parses the response into a structured safety verdict.
"""
from __future__ import annotations

import json
import logging
import re

import httpx

import reviewer_service.config as config

logger = logging.getLogger("reviewer_service.llm_client")

_VERDICTS = {"OK", "WARN", "BLOCK"}

_SYSTEM_PROMPT = """\
You are a blockchain transaction safety reviewer for an Ethereum payment system.
Your job is to analyze EIP-1559 transactions and return a structured JSON safety report.
Be concise and accurate. Return ONLY valid JSON — no markdown, no code fences, no extra text.
"""

_USER_PROMPT_TEMPLATE = """\
Analyze this Ethereum transaction for safety and return a JSON report.

Transaction details:
  Intent ID:              {intent_id}
  Chain ID:               {chain_id} ({chain_name})
  From:                   {from_address}
  To (recipient):         {to_address}
  Amount:                 {value_wei} wei ({eth_amount:.8f} ETH)
  Gas limit:              {gas_limit}
  Max fee per gas:        {max_fee_per_gas} wei ({max_fee_gwei:.4f} gwei)
  Max priority fee/gas:   {max_priority_fee_per_gas} wei ({priority_gwei:.4f} gwei)
  Current network base fee: {base_fee_wei} wei ({base_fee_gwei:.4f} gwei)
  Estimated total fee:    {estimated_fee_wei} wei ({estimated_fee_eth:.8f} ETH)

Check for:
1. Gas fee manipulation — is max_fee_per_gas unreasonably high vs the base fee?
   (> 3x base fee = WARN, > 10x base fee = BLOCK)
2. Unusual or suspicious transfer amount.
3. Any other transaction anomalies.

Return ONLY this JSON structure (no markdown):
{{
  "verdict": "OK",
  "reasons": [],
  "summary": "One-sentence summary.",
  "gas_assessment": {{
    "estimated_total_fee_wei": "{estimated_fee_wei}",
    "is_reasonable": true,
    "reference": "max_fee is within normal range of base fee"
  }}
}}

Verdict must be exactly one of: "OK", "WARN", or "BLOCK".
"""


def _build_prompt(draft_tx: dict, current_base_fee_wei: int) -> str:
    value_wei = int(draft_tx.get("value_wei", 0))
    gas_limit = int(draft_tx.get("gas_limit", 21_000))
    max_fee = int(draft_tx.get("max_fee_per_gas", 0))
    priority_fee = int(draft_tx.get("max_priority_fee_per_gas", 0))
    chain_id = draft_tx.get("chain_id", 11155111)
    chain_name = "Sepolia testnet" if chain_id == 11155111 else f"chain {chain_id}"
    estimated_fee_wei = gas_limit * max_fee

    return _USER_PROMPT_TEMPLATE.format(
        intent_id=draft_tx.get("intent_id", "unknown"),
        chain_id=chain_id,
        chain_name=chain_name,
        from_address=draft_tx.get("from_address", "unknown"),
        to_address=draft_tx.get("to", "unknown"),
        value_wei=value_wei,
        eth_amount=value_wei / 1e18,
        gas_limit=gas_limit,
        max_fee_per_gas=max_fee,
        max_fee_gwei=max_fee / 1e9,
        max_priority_fee_per_gas=priority_fee,
        priority_gwei=priority_fee / 1e9,
        base_fee_wei=current_base_fee_wei,
        base_fee_gwei=current_base_fee_wei / 1e9,
        estimated_fee_wei=estimated_fee_wei,
        estimated_fee_eth=estimated_fee_wei / 1e18,
    )


def _parse_llm_response(text: str, draft_tx: dict, current_base_fee_wei: int) -> dict:
    """
    Parse the LLM text response into a ReviewReport dict.
    Falls back to heuristic analysis if JSON parsing fails.
    """
    # Strip markdown code fences if present
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    text = text.strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Try to extract JSON from the response
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(0))
            except json.JSONDecodeError:
                logger.warning("LLM returned unparseable JSON — falling back to heuristics")
                return _heuristic_review(draft_tx, current_base_fee_wei)
        else:
            logger.warning("No JSON found in LLM response — falling back to heuristics")
            return _heuristic_review(draft_tx, current_base_fee_wei)

    # Validate and normalise verdict
    verdict = str(data.get("verdict", "WARN")).upper()
    if verdict not in _VERDICTS:
        logger.warning("LLM returned unknown verdict %r — defaulting to WARN", verdict)
        verdict = "WARN"

    reasons = data.get("reasons", [])
    if not isinstance(reasons, list):
        reasons = [str(reasons)]

    summary = str(data.get("summary", "Transaction reviewed by LLM."))

    gas_data = data.get("gas_assessment", {})
    gas_limit = int(draft_tx.get("gas_limit", 21_000))
    max_fee = int(draft_tx.get("max_fee_per_gas", 0))
    estimated_fee_wei = gas_limit * max_fee
    gas_assessment = {
        "estimated_total_fee_wei": str(gas_data.get("estimated_total_fee_wei", estimated_fee_wei)),
        "is_reasonable": bool(gas_data.get("is_reasonable", True)),
        "reference": str(gas_data.get("reference", "reviewed by LLM")),
    }

    return {
        "verdict": verdict,
        "reasons": reasons,
        "summary": summary,
        "gas_assessment": gas_assessment,
    }


# On testnets like Sepolia the base fee can drop to near-zero (< 1 gwei).
# In that scenario the standard EIP-1559 formula (max_fee = 2*base + tip)
# produces a huge ratio against base_fee even though the absolute fee is
# perfectly normal.  We floor the base fee at 1 gwei so the ratio check
# is only meaningful when the base fee is in a realistic range.
_MIN_BASE_FEE_WEI = 1_000_000_000  # 1 gwei


def _heuristic_review(draft_tx: dict, current_base_fee_wei: int) -> dict:
    """
    Fallback heuristic analysis when LLM is unavailable or returns bad output.
    """
    max_fee = int(draft_tx.get("max_fee_per_gas", 0))
    gas_limit = int(draft_tx.get("gas_limit", 21_000))
    estimated_fee_wei = gas_limit * max_fee
    reasons = []
    verdict = "OK"

    effective_base = max(current_base_fee_wei, _MIN_BASE_FEE_WEI)
    if current_base_fee_wei > 0:
        ratio = max_fee / effective_base
        if ratio > 10:
            verdict = "BLOCK"
            reasons.append(
                f"Gas fee manipulation: max_fee_per_gas is {ratio:.1f}x the current base fee"
            )
        elif ratio > 3:
            verdict = "WARN"
            reasons.append(
                f"Elevated gas fee: max_fee_per_gas is {ratio:.1f}x the current base fee"
            )

    return {
        "verdict": verdict,
        "reasons": reasons,
        "summary": "Heuristic review (LLM unavailable).",
        "gas_assessment": {
            "estimated_total_fee_wei": str(estimated_fee_wei),
            "is_reasonable": verdict != "BLOCK",
            "reference": "heuristic fallback",
        },
    }


async def review_transaction(
    intent_id: str,
    draft_tx: dict,
    current_base_fee_wei: int,
) -> dict:
    """
    Call Z.AI GLM-5 to review the transaction. Returns a dict with the
    review result fields (excluding intent_id and digest — caller adds those).

    Logs the model name and request_id for hackathon proof.
    """
    model = config.ZAI_MODEL
    prompt = _build_prompt(draft_tx, current_base_fee_wei)

    logger.info(
        "Sending review request to Z.AI: intent_id=%s model=%s endpoint=%s/chat/completions",
        intent_id,
        model,
        config.ZAI_API_BASE,
    )

    headers = {
        "Authorization": f"Bearer {config.ZAI_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.1,
    }

    timeout = httpx.Timeout(connect=10.0, read=config.ZAI_TIMEOUT_SECONDS, write=10.0, pool=5.0)

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                f"{config.ZAI_API_BASE}/chat/completions",
                headers=headers,
                json=payload,
            )
        logger.info(
            "Z.AI response: intent_id=%s model=%s status=%s",
            intent_id,
            model,
            resp.status_code,
        )
        resp.raise_for_status()
        body = resp.json()
        llm_text = body["choices"][0]["message"]["content"]
    except httpx.HTTPStatusError as exc:
        logger.error(
            "Z.AI HTTP error: intent_id=%s model=%s status=%s body=%s",
            intent_id,
            model,
            exc.response.status_code,
            exc.response.text[:300],
        )
        logger.warning("Falling back to heuristic review for intent_id=%s", intent_id)
        result = _heuristic_review(draft_tx, current_base_fee_wei)
        result["model_used"] = f"{model}:fallback-heuristic"
        return result
    except Exception as exc:
        logger.error(
            "Z.AI request failed: intent_id=%s model=%s error=%s",
            intent_id,
            model,
            exc,
        )
        logger.warning("Falling back to heuristic review for intent_id=%s", intent_id)
        result = _heuristic_review(draft_tx, current_base_fee_wei)
        result["model_used"] = f"{model}:fallback-heuristic"
        return result

    result = _parse_llm_response(llm_text, draft_tx, current_base_fee_wei)
    result["model_used"] = model

    logger.info(
        "Review complete: intent_id=%s model=%s verdict=%s",
        intent_id,
        model,
        result["verdict"],
    )
    return result

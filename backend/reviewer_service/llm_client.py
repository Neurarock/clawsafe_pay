"""
Z.AI / GLM-5 HTTP client for the reviewer_service.

Sends a transaction review prompt to the Z.AI chat completions API and
parses the response into a structured safety verdict.
"""
from __future__ import annotations

import asyncio
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
{calldata_section}
Check for:
1. Gas fee manipulation — is max_fee_per_gas unreasonably high vs the base fee?
   IMPORTANT: On testnets like Sepolia the base fee can drop to near-zero
   (single-digit wei).  When the base fee is below 1 gwei (1000000000 wei),
   use 1 gwei as the effective floor for ratio comparisons — a high ratio
   against a near-zero base fee is normal EIP-1559 behaviour, NOT manipulation.
   Only flag ratios computed against realistically-sized base fees.
   (> 3x effective base fee = WARN, > 10x effective base fee = BLOCK)
2. Unusual or suspicious transfer amount.
3. Any other transaction anomalies.
{calldata_checks}
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

_CALLDATA_SECTION_TEMPLATE = """\
  Calldata (hex):         {calldata}
  Agent's description:    {calldata_description}

"""

_CALLDATA_CHECKS = """\
4. Calldata analysis — independently decode the calldata hex for the contract at the "To" address:
   a. Identify the function selector (first 4 bytes) and what function it calls.
   b. Decode the key parameters (token addresses, amounts, recipients, deadlines).
   c. Verify the agent's description matches what the calldata actually does.
   d. Flag any discrepancy between the agent's description and the decoded calldata as WARN.
   e. Flag if calldata sends funds to an address not matching the stated recipient as BLOCK.
   Include your calldata interpretation in the "summary" field.
"""


def _build_prompt(draft_tx: dict, current_base_fee_wei: int, calldata_description: str = "") -> str:
    value_wei = int(draft_tx.get("value_wei", 0))
    gas_limit = int(draft_tx.get("gas_limit", 21_000))
    max_fee = int(draft_tx.get("max_fee_per_gas", 0))
    priority_fee = int(draft_tx.get("max_priority_fee_per_gas", 0))
    chain_id = draft_tx.get("chain_id", 11155111)
    chain_name = "Sepolia testnet" if chain_id == 11155111 else f"chain {chain_id}"
    estimated_fee_wei = gas_limit * max_fee

    calldata = draft_tx.get("data", "0x") or "0x"
    has_calldata = calldata not in ("0x", "")
    calldata_section = (
        _CALLDATA_SECTION_TEMPLATE.format(
            calldata=calldata,
            calldata_description=calldata_description or "(no description provided)",
        )
        if has_calldata else ""
    )
    calldata_checks = _CALLDATA_CHECKS if has_calldata else ""

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
        calldata_section=calldata_section,
        calldata_checks=calldata_checks,
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

    # Non-empty calldata cannot be verified without the LLM — always flag WARN
    calldata = draft_tx.get("data", "0x") or "0x"
    if calldata not in ("0x", ""):
        verdict = "WARN"
        reasons.append(
            "LLM unavailable: transaction contains calldata that could not be independently verified"
        )

    effective_base = max(current_base_fee_wei, _MIN_BASE_FEE_WEI)
    if current_base_fee_wei > 0:
        ratio = max_fee / effective_base
        if ratio > 10:
            verdict = "BLOCK"
            reasons.append(
                f"Gas fee manipulation: max_fee_per_gas is {ratio:.1f}x the current base fee"
            )
        elif ratio > 3 and verdict != "BLOCK":
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
    calldata_description: str = "",
) -> dict:
    """
    Call Z.AI GLM-5 to review the transaction. Returns a dict with the
    review result fields (excluding intent_id and digest — caller adds those).

    Logs the model name and request_id for hackathon proof.
    """
    model = config.ZAI_MODEL
    prompt = _build_prompt(draft_tx, current_base_fee_wei, calldata_description)

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


_FLOCK_CHAT_URL = "https://api.flock.io/v1/chat/completions"

_SEVERITY = {"BLOCK": 2, "WARN": 1, "OK": 0}


async def _review_transaction_flock(
    intent_id: str,
    draft_tx: dict,
    current_base_fee_wei: int,
    calldata_description: str = "",
) -> dict:
    """
    Call Flock API (kimi-k2.5) for an independent second review of the transaction.
    Uses the same prompt and response parser as the Z.AI reviewer.
    Falls back to heuristics if Flock is unavailable or not configured.
    """
    model = config.FLOCK_REVIEW_MODEL

    if not config.FLOCK_API_KEY:
        logger.warning(
            "FLOCK_API_KEY not set — skipping Flock review for intent_id=%s", intent_id
        )
        result = _heuristic_review(draft_tx, current_base_fee_wei)
        result["model_used"] = f"{model}:skipped-no-key"
        return result

    prompt = _build_prompt(draft_tx, current_base_fee_wei, calldata_description)

    logger.info(
        "Sending review request to Flock: intent_id=%s model=%s",
        intent_id,
        model,
    )

    headers = {
        "x-litellm-api-key": config.FLOCK_API_KEY,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.1,
    }

    timeout = httpx.Timeout(
        connect=10.0, read=config.FLOCK_REVIEW_TIMEOUT_SECONDS, write=10.0, pool=5.0
    )

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(_FLOCK_CHAT_URL, headers=headers, json=payload)
        logger.info(
            "Flock response: intent_id=%s model=%s status=%s",
            intent_id,
            model,
            resp.status_code,
        )
        resp.raise_for_status()
        body = resp.json()
        llm_text = body["choices"][0]["message"]["content"]
    except Exception as exc:
        logger.error(
            "Flock review failed: intent_id=%s model=%s error=%s — falling back to heuristics",
            intent_id,
            model,
            exc,
        )
        result = _heuristic_review(draft_tx, current_base_fee_wei)
        result["model_used"] = f"{model}:fallback-heuristic"
        return result

    result = _parse_llm_response(llm_text, draft_tx, current_base_fee_wei)
    result["model_used"] = model

    logger.info(
        "Flock review complete: intent_id=%s model=%s verdict=%s",
        intent_id,
        model,
        result["verdict"],
    )
    return result


def _reconcile_verdicts(zai_result: dict, flock_result: dict) -> dict:
    """
    Combine two independent review verdicts into a single final report.

    Rules:
    - If both agree → use that verdict.
    - If they disagree → take the more conservative (higher severity) verdict
      and log the disagreement prominently.
    - Reasons from both reviewers are included with model attribution.
    - Gas assessment is taken from the Z.AI result (primary reviewer).
    """
    zai_v = zai_result["verdict"]
    flock_v = flock_result["verdict"]
    models_agreed = zai_v == flock_v

    if models_agreed:
        final_verdict = zai_v
        agreement_note = f"Both reviewers agree: {final_verdict}"
    else:
        final_verdict = zai_v if _SEVERITY[zai_v] >= _SEVERITY[flock_v] else flock_v
        agreement_note = (
            f"Reviewers disagreed (Z.AI={zai_v}, Flock={flock_v}); "
            f"taking conservative verdict: {final_verdict}"
        )
        logger.warning(
            "REVIEWER DISAGREEMENT: Z.AI=%s Flock=%s → final=%s",
            zai_v,
            flock_v,
            final_verdict,
        )

    # Combine reasons with model attribution
    reasons: list[str] = []
    for r in zai_result.get("reasons", []):
        reasons.append(f"[Z.AI/{zai_result['model_used']}] {r}")
    for r in flock_result.get("reasons", []):
        reasons.append(f"[Flock/{flock_result['model_used']}] {r}")
    if not models_agreed:
        reasons.append(agreement_note)

    # Combine summaries
    zai_summary = zai_result.get("summary", "")
    flock_summary = flock_result.get("summary", "")
    if zai_summary == flock_summary or not flock_summary:
        summary = zai_summary
    else:
        summary = f"Z.AI: {zai_summary} | Flock: {flock_summary}"

    return {
        "verdict": final_verdict,
        "reasons": reasons,
        "summary": summary,
        "gas_assessment": zai_result.get("gas_assessment", {}),
        "models_agreed": models_agreed,
        "individual_verdicts": {"zai": zai_v, "flock": flock_v},
        "model_used": f"{zai_result['model_used']}+{flock_result['model_used']}",
    }


async def review_transaction_dual(
    intent_id: str,
    draft_tx: dict,
    current_base_fee_wei: int,
    calldata_description: str = "",
) -> dict:
    """
    Run Z.AI GLM and Flock kimi-k2.5 reviews in parallel, then reconcile.
    Returns a combined result dict with both verdicts and a final conservative verdict.
    """
    zai_result, flock_result = await asyncio.gather(
        review_transaction(intent_id, draft_tx, current_base_fee_wei, calldata_description),
        _review_transaction_flock(intent_id, draft_tx, current_base_fee_wei, calldata_description),
    )

    return _reconcile_verdicts(zai_result, flock_result)

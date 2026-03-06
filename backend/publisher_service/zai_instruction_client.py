"""
Z.AI GLM client for agentic transaction planning.

Given a natural-language instruction plus injected context (wallet balances,
recent trades, agent policy), Z.AI reasons about what on-chain action to take
and calls plan_transaction when ready.
"""
from __future__ import annotations

import json
import logging

import httpx

import publisher_service.config as config

logger = logging.getLogger("publisher_service.zai_instruction")

# Known Sepolia contract addresses injected into every call
_SEPOLIA_CONTRACTS = """\
Known Sepolia testnet contracts:
  Uniswap V3 SwapRouter02:  0x3bFA4769FB09eefC5a80d6E87c3B9C650f7Ae48
  Uniswap V3 QuoterV2:      0x61fFE014bA17989E743c5F6cB21bF9697530B21e
  WETH (Wrapped ETH):       0xfFf9976782d46CC05630D1f6eBAb18b2324d6B14
  USDC (Circle test):       0x1c7D4B196Cb0C7B01d743Fbc6116a902379C7238
  DAI (test):               0x68194a729C2450ad26072b3D33ADaCbcef39D574
"""

_SYSTEM_PROMPT_TEMPLATE = """\
You are an on-chain execution agent for ClawSafe Pay operating on Sepolia testnet.
Your job: understand the user's instruction, reason about the current wallet state and
recent history, then call plan_transaction with a concrete action plan.

CURRENT WALLET STATE ({from_address}):
{wallet_state}

RECENT TRADES (last 5):
{recent_trades}

AGENT POLICY:
  Allowed contracts: {allowed_contracts}
  Allowed assets:    {allowed_assets}
  Max per tx:        {max_amount_eth} ETH
  Approval mode:     {approval_mode}

{sepolia_contracts}

Rules:
- Only use contracts in allowed_contracts, or ["*"] means unrestricted.
- If allowed_contracts is ["*"], you may use well-known Sepolia contracts above.
- If the user hasn't specified an amount, ask before calling plan_transaction.
- Keep reasoning bullets concise (max 3 bullets).
- Call plan_transaction once you have enough info — do NOT ask for confirmation.
"""

_GREETING = "Hi! I'm your on-chain agent. Tell me what to do — e.g. \"buy WBTC with 0.005 ETH on Uniswap\" or \"send 0.001 ETH to alice\"."

_PLAN_TX_TOOL = {
    "type": "function",
    "function": {
        "name": "plan_transaction",
        "description": "Submit a concrete transaction plan once the agent has determined the right action.",
        "parameters": {
            "type": "object",
            "properties": {
                "to_address":  {"type": "string", "description": "Contract or recipient address (checksummed)"},
                "value_wei":   {"type": "string", "description": "Amount of ETH to send in wei as a string integer (e.g. '5000000000000000' for 0.005 ETH)."},
                "asset":       {"type": "string", "description": "Asset symbol being sent (e.g. ETH, USDC, WBTC)."},
                "note":        {"type": "string", "description": "Human-readable description of the action"},
                "reasoning":   {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 3},
                "needs_human": {"type": "boolean", "description": "True if this action should require human approval regardless of policy"},
            },
            "required": ["to_address", "value_wei", "asset", "note", "reasoning", "needs_human"],
        },
    },
}


def _format_wallet_state(balances: list[dict]) -> str:
    if not balances:
        return "  (no balance data available)"
    lines = []
    for b in balances:
        display = b.get("balance_display", "?")
        symbol = b.get("symbol", "ETH")
        lines.append(f"  {symbol}: {display}")
    return "\n".join(lines) if lines else "  (empty)"


def _format_recent_trades(intents: list[dict]) -> str:
    if not intents:
        return "  (no recent trades)"
    lines = []
    for i in intents[:5]:
        note = (i.get("note") or "")[:60]
        status = i.get("status", "?")
        amount_wei = i.get("amount_wei", "0")
        try:
            eth = int(amount_wei) / 1e18
        except (ValueError, TypeError):
            eth = 0
        lines.append(f"  [{status}] {eth:.4f} ETH — {note}")
    return "\n".join(lines)


async def instruction_chat(
    messages: list[dict],
    user_message: str,
    *,
    from_address: str,
    wallet_balances: list[dict],
    recent_intents: list[dict],
    agent_policy: dict,
) -> dict:
    """
    Continue a multi-turn agent instruction chat.

    Returns {"type": "message", "content": str, "messages": [...]}
    or      {"type": "plan",    "plan": {...},   "messages": [...]}
    """
    max_amount_wei = agent_policy.get("max_amount_wei", "0")
    try:
        max_eth = int(max_amount_wei) / 1e18 if max_amount_wei and max_amount_wei != "0" else "unlimited"
        max_amount_eth = f"{max_eth:.4f}" if isinstance(max_eth, float) else max_eth
    except (ValueError, TypeError):
        max_amount_eth = "unlimited"

    system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(
        from_address=from_address or "unknown",
        wallet_state=_format_wallet_state(wallet_balances),
        recent_trades=_format_recent_trades(recent_intents),
        allowed_contracts=json.dumps(agent_policy.get("allowed_contracts", ["*"])),
        allowed_assets=json.dumps(agent_policy.get("allowed_assets", ["*"])),
        max_amount_eth=max_amount_eth,
        approval_mode=agent_policy.get("approval_mode", "always_human"),
        sepolia_contracts=_SEPOLIA_CONTRACTS,
    )

    all_messages = [
        {"role": "system", "content": system_prompt},
        *messages,
        {"role": "user", "content": user_message},
    ]

    payload = {
        "model": config.ZAI_MODEL,
        "messages": all_messages,
        "tools": [_PLAN_TX_TOOL],
        "tool_choice": "auto",
        "temperature": 0.2,
    }
    headers = {
        "Authorization": f"Bearer {config.ZAI_API_KEY}",
        "Content-Type": "application/json",
    }
    timeout = httpx.Timeout(connect=10.0, read=config.ZAI_TIMEOUT_SECONDS, write=10.0, pool=5.0)

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(
            f"{config.ZAI_API_BASE}/chat/completions",
            headers=headers,
            json=payload,
        )

    logger.info(
        "Z.AI instruction chat: model=%s status=%s request_id=%s from=%s",
        config.ZAI_MODEL, resp.status_code,
        resp.headers.get("x-request-id", "?"),
        (from_address or "?")[:10],
    )
    resp.raise_for_status()

    choice = resp.json()["choices"][0]
    finish_reason = choice.get("finish_reason", "")
    message = choice["message"]

    updated_messages = [
        *messages,
        {"role": "user", "content": user_message},
    ]

    if finish_reason == "tool_calls" and message.get("tool_calls"):
        tool_call = message["tool_calls"][0]
        plan = json.loads(tool_call["function"]["arguments"])
        plan.setdefault("needs_human", True)
        plan.setdefault("reasoning", [])
        # Normalise value_wei to a clean integer string (Z.AI may return float/sci notation)
        try:
            plan["value_wei"] = str(int(float(plan.get("value_wei", "0"))))
        except (ValueError, TypeError):
            plan["value_wei"] = "0"
        summary = plan.get("note", "Transaction planned")
        updated_messages.append({"role": "assistant", "content": f"Plan ready: {summary}"})
        return {"type": "plan", "plan": plan, "messages": updated_messages}
    else:
        content = message.get("content", "")
        updated_messages.append({"role": "assistant", "content": content})
        return {"type": "message", "content": content, "messages": updated_messages}


def greeting() -> str:
    return _GREETING

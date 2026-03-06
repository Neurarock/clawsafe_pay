"""
Z.AI GLM client for AI-powered agent policy generation.
Calls the Z.AI chat completions API and parses the structured JSON response.
"""
from __future__ import annotations

import json
import logging
import re

import httpx

import publisher_service.config as config

logger = logging.getLogger("publisher_service.zai_policy")

_SYSTEM_PROMPT = """\
You are a crypto payment policy advisor for an AI agent authorization system.
Given an AI agent's stated goal, suggest appropriate spending controls and contract restrictions.
Respond ONLY with valid JSON — no markdown fences, no explanation outside the JSON object.

Required schema:
{
  "approval_mode": "always_human" | "auto_within_limits" | "human_if_above_threshold",
  "approval_threshold_wei": "<integer as string, 0 if mode is not human_if_above_threshold>",
  "window_limit_wei": "<integer as string, 0 if no cap>",
  "window_seconds": <integer, 0 if no window>,
  "max_amount_wei": "<integer as string, 0 = unlimited>",
  "daily_limit_wei": "<integer as string, 0 = unlimited>",
  "allowed_contracts": ["<checksummed address>", ...] or ["*"],
  "allowed_assets": ["<TOKEN_SYMBOL>", ...] or ["*"],
  "allowed_chains": ["<chain_slug>", ...] or ["*"],
  "reasoning": ["<bullet 1>", "<bullet 2>", "<bullet 3>"],
  "policy_summary": "<one concise sentence describing the overall policy>"
}

Asset/chain guidelines:
- Extract specific token symbols mentioned in the goal (e.g. "wBTC", "USDT", "ETH", "USDC", "SOL")
- Use uppercase for token symbols: "ETH", "WBTC", "USDT", "USDC", "DAI", "SOL", "BTC"
- If no specific assets mentioned, use ["*"]
- For chains: use slugs like "mainnet", "base", "sepolia", "solana", "arbitrum", "optimism". If all chains are allowed, use ["*"].
- If no specific chain mentioned or it's general DeFi, use ["*"]

Wei reference values:
  0.001 ETH = 1000000000000000
  0.01 ETH  = 10000000000000000
  0.05 ETH  = 50000000000000000
  0.1 ETH   = 100000000000000000
  0.5 ETH   = 500000000000000000
  1 ETH     = 1000000000000000000

Well-known mainnet contract addresses (use for suggestions):
  Uniswap V3 Router:     0xE592427A0AEce92De3Edee1F18E0157C05861564
  Uniswap Universal:     0x3fC91A3afd70395Cd496C647d5a6CC9D4B2b7FAD
  SushiSwap Router:      0xd9e1cE17f2641f24aE83637ab66a2cca9C378B9F
  Curve Router:          0x99a58482BD75cbab83b27EC03CA68fF489b5788f
  CoW Protocol:          0x9008D19f58AAbD9eD0D60971565AA8510560ab41
  1inch V5:              0x1111111254EEB25477B68fb85Ed929f73A960582
  OpenSea Seaport:       0x00000000000000ADc04C56Bf30aC9d3c0aAF14dC
  Blur Exchange:         0x000000000000Ad05Ccc4F10045630fb830B95127
  Aave V3 Pool:          0x87870Bca3F3fD6335C3F4ce8392D69350B4fA4E2
  Compound V3 USDC:      0xc3d688B66703497DAA19211EEdff47f25384cdc3
  Polymarket CTF:        0x4D97DCd97eC945f40cF65F87097ACe5EA0476045
  Pump.fun Program:      6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P

Policy guidelines:
- Personal/ecommerce bots: approval_mode = "always_human" or "human_if_above_threshold"; allowed_contracts = ["*"] (restrict by goal if specific)
- Automated trading bots: approval_mode = "auto_within_limits"; suggest specific DEX contracts
- Time-sensitive bots (NFT sniper, pump.fun): auto mode with tight window caps
- DeFi bots: suggest specific protocol contracts; require human for large amounts
- When uncertain, be conservative — require human approval
- Always provide exactly 3 reasoning bullets
"""


_CHAT_SYSTEM_PROMPT = """\
You are an AI agent policy advisor for ClawSafe Pay, a crypto payment authorization platform.
Your job: gather information to configure a new AI agent through natural conversation, then call create_agent_draft.

Collect in order (ask 1-2 things per turn, be concise):
1. Agent name — display name for the bot
2. Bot type — one of: personal, ecommerce, dca_trader, spot_trader, nft_sniper, pump_fun_sniper, polymarket_copytrader, defi_borrower, custom
3. Bot goal — mission statement (1-2 sentences)
4. Allowed assets — token symbols (ETH, USDC, WBTC, USDT...) or ["*"] for all
5. Allowed contracts — specific smart contract addresses or ["*"] for unrestricted
6. Spending policy — approval mode + ETH limits (you convert to wei)

Approval modes: always_human | auto_within_limits | human_if_above_threshold
Wei: 0.01 ETH=10000000000000000, 0.05 ETH=50000000000000000, 0.1 ETH=100000000000000000, 0.5 ETH=500000000000000000, 1 ETH=1000000000000000000

Bot type hints:
- personal/ecommerce: always_human or human_if_above_threshold; contracts=["*"]
- trading (spot/dca): auto_within_limits; Uniswap V3=0xE592427A0AEce92De3Edee1F18E0157C05861564
- nft_sniper: human_if_above_threshold, tight hourly window cap
- pump_fun_sniper: auto_within_limits, 5min window, 0.05 ETH cap; Program=6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P
- defi_borrower: human_if_above_threshold; Aave V3=0x87870Bca3F3fD6335C3F4ce8392D69350B4fA4E2

Once you have all required info, call create_agent_draft immediately — do NOT ask for confirmation.
Keep replies under 3 sentences. Be friendly but efficient.
"""

_CREATE_AGENT_TOOL = {
    "type": "function",
    "function": {
        "name": "create_agent_draft",
        "description": "Submit the complete agent configuration once all info is gathered.",
        "parameters": {
            "type": "object",
            "properties": {
                "name":                   {"type": "string"},
                "bot_type":               {"type": "string", "enum": ["personal","ecommerce","dca_trader","spot_trader","nft_sniper","pump_fun_sniper","polymarket_copytrader","defi_borrower","custom"]},
                "bot_goal":               {"type": "string"},
                "allowed_assets":         {"type": "array", "items": {"type": "string"}},
                "allowed_chains":         {"type": "array", "items": {"type": "string"}},
                "allowed_contracts":      {"type": "array", "items": {"type": "string"}},
                "approval_mode":          {"type": "string", "enum": ["always_human","auto_within_limits","human_if_above_threshold"]},
                "approval_threshold_wei": {"type": "string"},
                "window_limit_wei":       {"type": "string"},
                "window_seconds":         {"type": "integer"},
                "max_amount_wei":         {"type": "string"},
                "daily_limit_wei":        {"type": "string"},
                "policy_summary":         {"type": "string"},
                "reasoning":              {"type": "array", "items": {"type": "string"}, "minItems": 3, "maxItems": 3},
            },
            "required": ["name","bot_type","bot_goal","approval_mode","allowed_assets","allowed_chains",
                         "allowed_contracts","approval_threshold_wei","window_limit_wei","window_seconds",
                         "max_amount_wei","daily_limit_wei","policy_summary","reasoning"],
        },
    },
}


async def policy_chat(messages: list[dict], user_message: str) -> dict:
    """
    Continue a multi-turn policy setup chat.

    Returns {"type": "message", "content": str, "messages": [...]}
    or      {"type": "draft",   "draft": {...},  "messages": [...]}
    """
    all_messages = [
        {"role": "system", "content": _CHAT_SYSTEM_PROMPT},
        *messages,
        {"role": "user", "content": user_message},
    ]

    payload = {
        "model": config.ZAI_MODEL,
        "messages": all_messages,
        "tools": [_CREATE_AGENT_TOOL],
        "tool_choice": "auto",
        "temperature": 0.3,
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
        "Z.AI policy chat: model=%s status=%s request_id=%s",
        config.ZAI_MODEL, resp.status_code, resp.headers.get("x-request-id", "?"),
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
        draft = json.loads(tool_call["function"]["arguments"])
        # Ensure all optional fields have defaults
        draft.setdefault("allowed_assets",         ["*"])
        draft.setdefault("allowed_chains",          ["*"])
        draft.setdefault("allowed_contracts",       ["*"])
        draft.setdefault("approval_threshold_wei",  "0")
        draft.setdefault("window_limit_wei",        "0")
        draft.setdefault("window_seconds",          0)
        draft.setdefault("max_amount_wei",          "0")
        draft.setdefault("daily_limit_wei",         "0")
        draft.setdefault("policy_summary",          "")
        draft.setdefault("reasoning",               [])
        updated_messages.append({"role": "assistant", "content": "✅ All set! Review your policy in the form below."})
        return {"type": "draft", "draft": draft, "messages": updated_messages}
    else:
        content = message.get("content", "")
        updated_messages.append({"role": "assistant", "content": content})
        return {"type": "message", "content": content, "messages": updated_messages}


async def generate_policy(
    bot_goal: str,
    bot_type: str,
    allowed_assets: list[str],
    allowed_chains: list[str],
) -> dict:
    """
    Call Z.AI GLM to generate a policy recommendation for an agent.

    Returns a dict matching GeneratePolicyResponse fields (plus model_used).
    Raises httpx.HTTPError or ValueError on failure.
    """
    user_msg = (
        f"Bot type: {bot_type}\n"
        f"Goal: {bot_goal}\n"
        f"Assets: {', '.join(allowed_assets)}\n"
        f"Chains: {', '.join(allowed_chains)}"
    )

    payload = {
        "model": config.ZAI_MODEL,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        "temperature": 0.2,
    }
    headers = {
        "Authorization": f"Bearer {config.ZAI_API_KEY}",
        "Content-Type": "application/json",
    }
    timeout = httpx.Timeout(
        connect=10.0, read=config.ZAI_TIMEOUT_SECONDS, write=10.0, pool=5.0
    )

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(
            f"{config.ZAI_API_BASE}/chat/completions",
            headers=headers,
            json=payload,
        )

    request_id = resp.headers.get("x-request-id", "?")
    logger.info(
        "Z.AI policy generation: model=%s status=%s request_id=%s",
        config.ZAI_MODEL, resp.status_code, request_id,
    )
    resp.raise_for_status()

    content: str = resp.json()["choices"][0]["message"]["content"]

    # Strip markdown code fences if model wraps response
    content = re.sub(r"^```[a-z]*\s*", "", content.strip())
    content = re.sub(r"\s*```$", "", content.strip())

    try:
        result = json.loads(content)
    except json.JSONDecodeError:
        # Last resort: extract first JSON object from response
        m = re.search(r"\{[\s\S]*\}", content)
        if not m:
            raise ValueError(f"Z.AI returned non-JSON response: {content[:200]}")
        result = json.loads(m.group(0))

    result["model_used"] = config.ZAI_MODEL
    # Ensure new fields have fallbacks if model omits them
    result.setdefault("allowed_assets", ["*"])
    result.setdefault("allowed_chains", ["*"])
    return result

"""
Token registry — maps (chain_id, asset_symbol) to deployment details.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class TokenConfig:
    """Metadata for a token deployment on a specific chain."""

    symbol: str              # e.g. "USDC"
    name: str                # e.g. "USD Coin"
    chain_id: str            # e.g. "sepolia", "solana-devnet"
    contract_address: str    # on-chain address (0x… for EVM, base58 for Solana, …)
    decimals: int            # 6 for USDC/USDT, 18 for DAI, etc.
    transfer_method: str     # "erc20" | "spl" | "cardano-native" | "omni" | …
    is_testnet: bool = True
    extra: dict[str, Any] = field(default_factory=dict)


# ── Private store ────────────────────────────────────────────────────────────

_tokens: dict[tuple[str, str], TokenConfig] = {}  # (chain_id, symbol) → TokenConfig


# ── Public API ───────────────────────────────────────────────────────────────


def register_token(cfg: TokenConfig) -> None:
    """Register a token deployment."""
    _tokens[(cfg.chain_id, cfg.symbol.upper())] = cfg


def get_token(chain_id: str, symbol: str) -> TokenConfig:
    """
    Look up a token on a specific chain.

    Raises ``KeyError`` if not found.
    """
    key = (chain_id, symbol.upper())
    if key not in _tokens:
        raise KeyError(f"Token {symbol!r} not registered on chain {chain_id!r}")
    return _tokens[key]


def list_tokens(chain_id: str | None = None) -> list[TokenConfig]:
    """
    List all registered tokens, optionally filtered by chain.
    """
    if chain_id is None:
        return list(_tokens.values())
    return [t for t in _tokens.values() if t.chain_id == chain_id]

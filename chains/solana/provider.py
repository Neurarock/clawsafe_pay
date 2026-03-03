"""
Solana RPC provider — placeholder.

TODO: Implement using ``solana-py`` or ``solders``.
"""

from __future__ import annotations

from typing import Any

from chains.base import ChainProvider


class SolanaProvider(ChainProvider):
    """Solana JSON-RPC provider (not yet implemented)."""

    def __init__(self, rpc_url: str) -> None:
        self._rpc_url = rpc_url

    async def get_balance(self, address: str) -> int:
        raise NotImplementedError("Solana provider not yet implemented")

    async def get_nonce(self, address: str) -> int:
        # Solana doesn't use sequential nonces — it uses recent blockhash
        raise NotImplementedError("Solana provider not yet implemented")

    async def get_fee_estimate(self) -> dict[str, Any]:
        raise NotImplementedError("Solana provider not yet implemented")

    async def broadcast(self, raw_tx: bytes) -> str:
        raise NotImplementedError("Solana provider not yet implemented")

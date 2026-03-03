"""
Zcash RPC provider — placeholder.

TODO: Implement using ``zcash-cli`` RPC or a Zcash REST API.
Needs to support both transparent and shielded balance queries.
"""

from __future__ import annotations

from typing import Any

from chains.base import ChainProvider


class ZcashProvider(ChainProvider):
    """Zcash provider (not yet implemented)."""

    def __init__(self, rpc_url: str | None = None) -> None:
        self._rpc_url = rpc_url

    async def get_balance(self, address: str) -> int:
        raise NotImplementedError("Zcash provider not yet implemented")

    async def get_nonce(self, address: str) -> int:
        return 0  # UTXO-based

    async def get_fee_estimate(self) -> dict[str, Any]:
        raise NotImplementedError("Zcash provider not yet implemented")

    async def broadcast(self, raw_tx: bytes) -> str:
        raise NotImplementedError("Zcash provider not yet implemented")

"""
Cardano provider — placeholder.

TODO: Implement using ``pycardano`` + Blockfrost/Ogmios backend.
"""

from __future__ import annotations

from typing import Any

from chains.base import ChainProvider


class CardanoProvider(ChainProvider):
    """Cardano provider (not yet implemented)."""

    def __init__(self, api_url: str | None = None, api_key: str = "") -> None:
        self._api_url = api_url
        self._api_key = api_key

    async def get_balance(self, address: str) -> int:
        raise NotImplementedError("Cardano provider not yet implemented")

    async def get_nonce(self, address: str) -> int:
        # eUTxO model — no sequential nonces
        return 0

    async def get_fee_estimate(self) -> dict[str, Any]:
        # TODO: return {"lovelace_per_byte": int, "price_mem": float, "price_step": float}
        raise NotImplementedError("Cardano provider not yet implemented")

    async def broadcast(self, raw_tx: bytes) -> str:
        raise NotImplementedError("Cardano provider not yet implemented")

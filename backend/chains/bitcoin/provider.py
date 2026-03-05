"""
Bitcoin RPC / Electrum / API provider — placeholder.

TODO: Implement using ``python-bitcoinrpc``, ``electrum``, or a
block explorer REST API (e.g. mempool.space, blockstream.info).
"""

from __future__ import annotations

from typing import Any

from chains.base import ChainProvider


class BitcoinProvider(ChainProvider):
    """Bitcoin provider (not yet implemented)."""

    def __init__(self, rpc_url: str | None = None) -> None:
        self._rpc_url = rpc_url

    async def get_balance(self, address: str) -> int:
        raise NotImplementedError("Bitcoin provider not yet implemented")

    async def get_nonce(self, address: str) -> int:
        # UTXO chains do not use sequential nonces
        return 0

    async def get_fee_estimate(self) -> dict[str, Any]:
        # TODO: return {"sat_per_vbyte": int}
        raise NotImplementedError("Bitcoin provider not yet implemented")

    async def broadcast(self, raw_tx: bytes) -> str:
        raise NotImplementedError("Bitcoin provider not yet implemented")

"""
EVM chain provider — wraps web3.py for balance, nonce, fee, and broadcast.

This delegates to the existing ``transaction_builder.provider.Web3Provider``
for nonce + gas queries, and adds balance + broadcast support.
"""

from __future__ import annotations

from typing import Any

from chains.base import ChainProvider


class EVMProvider(ChainProvider):
    """
    Live EVM provider backed by web3.py ``AsyncHTTPProvider``.

    Usage::

        provider = EVMProvider("https://ethereum-sepolia-rpc.publicnode.com")
    """

    def __init__(self, rpc_url: str) -> None:
        from web3 import AsyncWeb3
        self._w3 = AsyncWeb3(AsyncWeb3.AsyncHTTPProvider(rpc_url))

    async def get_balance(self, address: str) -> int:
        addr = self._w3.to_checksum_address(address)
        return await self._w3.eth.get_balance(addr)

    async def get_nonce(self, address: str) -> int:
        addr = self._w3.to_checksum_address(address)
        return await self._w3.eth.get_transaction_count(addr, "pending")

    async def get_fee_estimate(self) -> dict[str, Any]:
        block = await self._w3.eth.get_block("pending")
        base_fee = block.get("baseFeePerGas", 0)
        priority_fee = await self._w3.eth.max_priority_fee
        return {
            "base_fee_wei": int(base_fee),
            "priority_fee_wei": int(priority_fee),
        }

    async def broadcast(self, raw_tx: bytes) -> str:
        tx_hash = await self._w3.eth.send_raw_transaction(raw_tx)
        h = tx_hash.hex() if isinstance(tx_hash, bytes) else str(tx_hash)
        return h if h.startswith("0x") else "0x" + h

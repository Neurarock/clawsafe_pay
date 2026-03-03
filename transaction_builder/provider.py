"""
Provider abstraction for on-chain state queries.

The ProviderInterface is dependency-injected into the builder, making it trivial
to swap in a mock during tests without hitting a real RPC.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from .models import ProviderError


@dataclass
class GasEstimate:
    """Current gas market data fetched from the chain."""

    base_fee_wei: int          # baseFeePerGas from the pending block
    max_priority_fee_wei: int  # suggested maxPriorityFeePerGas from the node


class ProviderInterface(ABC):
    """Abstract interface for on-chain state queries. Implement for real or mock use."""

    @abstractmethod
    async def get_nonce(self, address: str) -> int:
        """Return the pending-state nonce for the given address."""
        ...

    @abstractmethod
    async def get_gas_estimate(self) -> GasEstimate:
        """Return the current base fee and suggested priority fee."""
        ...


class Web3Provider(ProviderInterface):
    """
    Live provider backed by a Web3.py AsyncHTTPProvider.

    Usage:
        provider = Web3Provider("https://sepolia.infura.io/v3/<KEY>")
    """

    def __init__(self, rpc_url: str) -> None:
        try:
            from web3 import AsyncWeb3
        except ImportError as exc:
            raise ImportError(
                "web3 is required for Web3Provider. "
                "Install it: pip install web3"
            ) from exc
        self._w3 = AsyncWeb3(AsyncWeb3.AsyncHTTPProvider(rpc_url))

    async def get_nonce(self, address: str) -> int:
        try:
            return await self._w3.eth.get_transaction_count(
                self._w3.to_checksum_address(address), "pending"
            )
        except Exception as exc:
            raise ProviderError(f"Failed to fetch nonce for {address}: {exc}") from exc

    async def get_gas_estimate(self) -> GasEstimate:
        try:
            block = await self._w3.eth.get_block("pending")
            base_fee = block.get("baseFeePerGas")
            if base_fee is None:
                raise ProviderError(
                    "Block is missing baseFeePerGas — confirm this is an EIP-1559 network"
                )
            priority_fee = await self._w3.eth.max_priority_fee
            return GasEstimate(
                base_fee_wei=int(base_fee),
                max_priority_fee_wei=int(priority_fee),
            )
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(f"Failed to fetch gas estimate: {exc}") from exc

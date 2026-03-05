"""
chains.base — Abstract base classes for multi-chain support.

Every chain implementation must provide concrete subclasses of:

    ChainConfig      static metadata (chain ID, explorer URL, address format, …)
    ChainProvider    on-chain read queries (balance, fees, broadcast)
    TxBuilder        unsigned transaction construction
    TxSigner         local signing of raw transactions

These ABCs define the interface contract that the publisher_service
orchestrator depends on.  By programming against these abstractions the
pipeline can support EVM, Solana, Bitcoin, Zcash, Cardano, and any future
chain without changing the core orchestration logic.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


# ── Chain Configuration ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class ChainConfig:
    """
    Immutable metadata describing a single chain (or network).

    Every chain implementation must define one of these and register it.
    """

    chain_id: str                          # machine-readable slug, e.g. "sepolia", "base", "solana-devnet"
    display_name: str                      # human-readable, e.g. "Sepolia Testnet"
    chain_family: str                      # "evm" | "solana" | "utxo" | "cardano"
    native_asset: str                      # ticker of the native gas token, e.g. "ETH", "SOL", "BTC"
    address_regex: re.Pattern = field(     # compiled regex that valid addresses must match
        default_factory=lambda: re.compile(r"^0x[0-9a-fA-F]{40}$"),
    )
    explorer_tx_url: str = ""              # f-string template with {tx_hash}, e.g. "https://sepolia.etherscan.io/tx/{tx_hash}"
    explorer_addr_url: str = ""            # f-string template with {address}
    default_rpc_url: str | None = None     # optional default public RPC
    is_testnet: bool = True
    decimals: int = 18                     # native asset decimals (ETH=18, BTC=8, SOL=9, ADA=6)
    extra: dict[str, Any] = field(         # chain-specific extras (e.g. EVM numeric chain_id)
        default_factory=dict,
    )

    def validate_address(self, address: str) -> bool:
        """Return True if *address* matches this chain's format."""
        return bool(self.address_regex.match(address))


# ── Chain Provider (on-chain reads + broadcast) ──────────────────────────────


class ChainProvider(ABC):
    """Abstract interface for querying on-chain state and broadcasting."""

    @abstractmethod
    async def get_balance(self, address: str) -> int:
        """Return the native-asset balance (in smallest unit) for *address*."""
        ...

    @abstractmethod
    async def get_nonce(self, address: str) -> int:
        """
        Return the next usable nonce/sequence number for *address*.

        For UTXO chains this may return 0 (unused); the builder handles
        UTXO selection internally.
        """
        ...

    @abstractmethod
    async def get_fee_estimate(self) -> dict[str, Any]:
        """
        Return chain-specific fee market data.

        For EVM: ``{"base_fee_wei": int, "priority_fee_wei": int}``
        For Bitcoin/Zcash: ``{"sat_per_vbyte": int}``
        For Solana: ``{"lamports_per_signature": int}``
        For Cardano: ``{"lovelace_per_byte": int}``
        """
        ...

    @abstractmethod
    async def broadcast(self, raw_tx: bytes) -> str:
        """
        Submit a **signed** raw transaction to the network.

        Returns the on-chain transaction hash / signature string.
        """
        ...


# ── Transaction Builder ─────────────────────────────────────────────────────


@dataclass
class UnsignedTx:
    """
    Chain-agnostic container for an unsigned transaction.

    Each chain fills in ``chain_id``, ``payload`` (chain-specific dict),
    and ``digest`` (the bytes that must be signed).
    """

    chain_id: str
    intent_id: str
    from_address: str
    to_address: str
    value_raw: str        # amount in smallest denomination, as decimal string
    digest: bytes         # the signing payload / hash
    payload: dict         # chain-specific unsigned tx dict
    expires_at: str = ""  # ISO-8601 expiry


class TxBuilder(ABC):
    """Abstract interface for constructing unsigned transactions."""

    @abstractmethod
    async def build(
        self,
        *,
        chain_config: ChainConfig,
        provider: ChainProvider,
        from_address: str,
        to_address: str,
        value_raw: str,
        asset: str = "",
        data: str = "",
        memo: str = "",
    ) -> UnsignedTx:
        """
        Build an unsigned transaction.

        Parameters
        ----------
        chain_config : Static chain metadata.
        provider     : Live on-chain state source.
        from_address : Sender wallet address.
        to_address   : Recipient address.
        value_raw    : Amount in smallest denomination (wei, lamports, satoshi…).
        asset        : Asset ticker ("ETH", "USDC", …). Empty → native asset.
        data         : Optional calldata / memo payload.
        memo         : Optional human-readable memo (Solana memo program, OP_RETURN, …).
        """
        ...


# ── Transaction Signer ──────────────────────────────────────────────────────


@dataclass
class SignedTx:
    """Chain-agnostic container for a signed transaction."""

    chain_id: str
    tx_hash: str          # 0x-prefixed or base58 depending on chain
    raw_tx: bytes         # serialised signed transaction bytes
    from_address: str
    to_address: str
    value_raw: str


class TxSigner(ABC):
    """Abstract interface for signing transactions."""

    @abstractmethod
    async def sign(
        self,
        unsigned_tx: UnsignedTx,
        private_key: str,
    ) -> SignedTx:
        """
        Sign *unsigned_tx* with *private_key*.

        Returns a ``SignedTx`` whose ``raw_tx`` is ready for broadcast.
        """
        ...

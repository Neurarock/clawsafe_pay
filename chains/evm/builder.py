"""
EVM transaction builder — wraps the existing ``transaction_builder`` package.

For native ETH transfers this delegates directly to ``build_draft_tx``.
Future: add ERC-20 token transfer support via calldata encoding.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any

from chains.base import ChainConfig, ChainProvider, TxBuilder, UnsignedTx


class EVMTxBuilder(TxBuilder):
    """
    Build unsigned EIP-1559 transactions for any EVM chain.

    Delegates to ``transaction_builder.build_draft_tx`` for the existing
    Sepolia implementation, making it available through the multi-chain
    registry interface.
    """

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
        """Build an unsigned EIP-1559 native transfer (or ERC-20 in the future)."""
        from transaction_builder.builder import build_draft_tx
        from transaction_builder.models import PaymentIntent, PolicyConfig
        from transaction_builder.provider import Web3Provider

        # For now, use the existing transaction_builder pipeline.
        # Build a PaymentIntent compatible with the legacy builder.
        intent = PaymentIntent(
            intent_id="chain-registry-build",
            from_user="",
            to_user="",
            chain="sepolia",  # legacy field, builder ignores it
            asset=asset or chain_config.native_asset,
            amount_wei=value_raw,
            to_address=to_address,
        )

        # Use the legacy Web3Provider for nonce/gas queries
        rpc_url = chain_config.default_rpc_url or ""
        legacy_provider = Web3Provider(rpc_url)

        evm_chain_id = chain_config.extra.get("evm_chain_id", 11155111)
        policy = PolicyConfig(
            allowed_chain_ids=[evm_chain_id],
        )

        draft = await build_draft_tx(intent, legacy_provider, from_address, policy)

        return UnsignedTx(
            chain_id=chain_config.chain_id,
            intent_id=draft.intent_id,
            from_address=draft.from_address,
            to_address=draft.to,
            value_raw=draft.value_wei,
            digest=bytes.fromhex(draft.digest.removeprefix("0x")),
            payload={
                "type": "eip1559",
                "chain_id": draft.chain_id,
                "nonce": draft.nonce,
                "gas_limit": draft.gas_limit,
                "max_fee_per_gas": draft.max_fee_per_gas,
                "max_priority_fee_per_gas": draft.max_priority_fee_per_gas,
                "to": draft.to,
                "value": draft.value_wei,
                "data": draft.data,
            },
            expires_at=draft.expires_at.isoformat(),
        )

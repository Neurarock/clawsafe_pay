"""
Solana transaction builder — placeholder.

TODO: Build Solana system-program transfer instructions and
SPL Token transfer instructions for USDC/USDT.
"""

from __future__ import annotations

from chains.base import ChainConfig, ChainProvider, TxBuilder, UnsignedTx


class SolanaTxBuilder(TxBuilder):
    """Build unsigned Solana transactions (not yet implemented)."""

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
        # TODO:
        # 1. Fetch recent blockhash from provider
        # 2. Build SystemProgram.transfer instruction (native SOL)
        #    OR SPL Token transfer instruction (USDC/USDT)
        # 3. If memo is provided, add Memo program instruction
        # 4. Serialize as unsigned Transaction
        raise NotImplementedError("Solana builder not yet implemented")

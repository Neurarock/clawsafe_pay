"""
Zcash transaction builder — placeholder.

TODO: Support both transparent (t-addr → t-addr) and shielded
(z-addr → z-addr) transaction construction.  Shielded transactions
require zk-SNARK proof generation.
"""

from __future__ import annotations

from chains.base import ChainConfig, ChainProvider, TxBuilder, UnsignedTx


class ZcashTxBuilder(TxBuilder):
    """Build unsigned Zcash transactions (not yet implemented)."""

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
        # 1. Determine tx type: transparent or shielded
        # 2. Transparent: UTXO selection similar to Bitcoin
        # 3. Shielded: build Sapling spend/output descriptions with memo
        # 4. Compute fee and change
        raise NotImplementedError("Zcash builder not yet implemented")

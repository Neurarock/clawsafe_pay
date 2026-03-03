"""
Cardano transaction builder — placeholder.

TODO: Build Cardano transactions using pycardano.  Handle UTxO
selection, min-ADA requirements, native token bundles, and
deterministic fee calculation.
"""

from __future__ import annotations

from chains.base import ChainConfig, ChainProvider, TxBuilder, UnsignedTx


class CardanoTxBuilder(TxBuilder):
    """Build unsigned Cardano transactions (not yet implemented)."""

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
        # 1. Query UTxOs at from_address (via Blockfrost / Ogmios)
        # 2. Coin selection (largest-first or random-improve)
        # 3. Build transaction body: inputs, outputs, fee, ttl
        # 4. If native token, add multi-asset output
        # 5. If memo, add auxiliary data (metadata)
        # 6. Calculate min fee deterministically
        # 7. Serialize and compute tx body hash for signing
        raise NotImplementedError("Cardano builder not yet implemented")

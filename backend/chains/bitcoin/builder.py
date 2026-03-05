"""
Bitcoin transaction builder — placeholder.

TODO: Implement UTXO selection, P2WPKH output construction, fee
estimation (sat/vByte × tx_size), and change output calculation.
"""

from __future__ import annotations

from chains.base import ChainConfig, ChainProvider, TxBuilder, UnsignedTx


class BitcoinTxBuilder(TxBuilder):
    """Build unsigned Bitcoin transactions (not yet implemented)."""

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
        # 1. Fetch UTXOs for from_address
        # 2. Select UTXOs (coin selection algorithm)
        # 3. Build outputs: recipient + change
        # 4. Estimate vSize and compute fee (sat_per_vbyte × vsize)
        # 5. If memo, add OP_RETURN output
        # 6. Serialize unsigned tx and compute sighash
        raise NotImplementedError("Bitcoin builder not yet implemented")

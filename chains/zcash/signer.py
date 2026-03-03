"""
Zcash transaction signer — placeholder.

TODO: Sign transparent inputs (secp256k1) and shielded
spend descriptions (Sapling proving key).
"""

from __future__ import annotations

from chains.base import SignedTx, TxSigner, UnsignedTx


class ZcashTxSigner(TxSigner):
    """Sign Zcash transactions (not yet implemented)."""

    async def sign(
        self,
        unsigned_tx: UnsignedTx,
        private_key: str,
    ) -> SignedTx:
        raise NotImplementedError("Zcash signer not yet implemented")

"""
Bitcoin transaction signer — placeholder.

TODO: Sign inputs using ECDSA secp256k1 (BIP-143 for SegWit).
"""

from __future__ import annotations

from chains.base import SignedTx, TxSigner, UnsignedTx


class BitcoinTxSigner(TxSigner):
    """Sign Bitcoin transactions (not yet implemented)."""

    async def sign(
        self,
        unsigned_tx: UnsignedTx,
        private_key: str,
    ) -> SignedTx:
        # TODO:
        # 1. Decode WIF private key
        # 2. For each input, compute BIP-143 sighash and sign with secp256k1
        # 3. Attach witness data (SegWit) or scriptSig (legacy)
        # 4. Serialize final signed tx
        raise NotImplementedError("Bitcoin signer not yet implemented")

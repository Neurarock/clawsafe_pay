"""
Cardano transaction signer — placeholder.

TODO: Sign the transaction body hash using Ed25519.
"""

from __future__ import annotations

from chains.base import SignedTx, TxSigner, UnsignedTx


class CardanoTxSigner(TxSigner):
    """Sign Cardano transactions (not yet implemented)."""

    async def sign(
        self,
        unsigned_tx: UnsignedTx,
        private_key: str,
    ) -> SignedTx:
        # TODO:
        # 1. Decode Ed25519 signing key from private_key (hex/bech32)
        # 2. Sign tx body hash (unsigned_tx.digest) with Ed25519
        # 3. Build TransactionWitnessSet with VKeyWitness
        # 4. Assemble signed Transaction (body + witness_set + auxiliary_data)
        # 5. Serialize to CBOR bytes
        raise NotImplementedError("Cardano signer not yet implemented")

"""
Solana transaction signer — placeholder.

TODO: Sign Solana transactions using Ed25519 keypairs.
"""

from __future__ import annotations

from chains.base import SignedTx, TxSigner, UnsignedTx


class SolanaTxSigner(TxSigner):
    """Sign Solana transactions (not yet implemented)."""

    async def sign(
        self,
        unsigned_tx: UnsignedTx,
        private_key: str,
    ) -> SignedTx:
        # TODO:
        # 1. Deserialize private_key as Ed25519 Keypair (base58 or bytes)
        # 2. Sign the serialised message from unsigned_tx.digest
        # 3. Attach signature and return serialised signed tx
        raise NotImplementedError("Solana signer not yet implemented")

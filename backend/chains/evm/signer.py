"""
EVM transaction signer — wraps ``eth_account.Account.sign_transaction``.

Signs an EIP-1559 transaction dict and returns a ``SignedTx`` ready for
broadcast via ``ChainProvider.broadcast()``.
"""

from __future__ import annotations

from chains.base import ChainConfig, SignedTx, TxSigner, UnsignedTx


class EVMTxSigner(TxSigner):
    """Sign EIP-1559 transactions using eth-account."""

    async def sign(
        self,
        unsigned_tx: UnsignedTx,
        private_key: str,
    ) -> SignedTx:
        from eth_account import Account
        from web3 import Web3

        payload = unsigned_tx.payload
        to_checksummed = Web3.to_checksum_address(payload["to"])

        tx_dict = {
            "type": 2,
            "chainId": payload["chain_id"],
            "nonce": payload["nonce"],
            "to": to_checksummed,
            "value": int(payload["value"]),
            "gas": payload["gas_limit"],
            "maxFeePerGas": int(payload["max_fee_per_gas"]),
            "maxPriorityFeePerGas": int(payload["max_priority_fee_per_gas"]),
            "data": (
                bytes.fromhex(payload["data"][2:])
                if payload.get("data", "0x").startswith("0x") and len(payload.get("data", "")) > 2
                else b""
            ),
        }

        signed = Account.sign_transaction(tx_dict, private_key)
        raw = (
            signed.raw_transaction
            if isinstance(signed.raw_transaction, bytes)
            else bytes.fromhex(signed.raw_transaction.removeprefix("0x"))
        )
        tx_hash = signed.hash.hex() if isinstance(signed.hash, bytes) else str(signed.hash)
        if not tx_hash.startswith("0x"):
            tx_hash = "0x" + tx_hash

        return SignedTx(
            chain_id=unsigned_tx.chain_id,
            tx_hash=tx_hash,
            raw_tx=raw,
            from_address=unsigned_tx.from_address,
            to_address=unsigned_tx.to_address,
            value_raw=unsigned_tx.value_raw,
        )

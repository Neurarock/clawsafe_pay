"""
Core signing logic.

Builds, signs and broadcasts a Sepolia EIP-1559 transaction using web3.py + eth-account.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from web3 import Web3, AsyncWeb3
from eth_account import Account

from signer_service.config import WALLET_ADDRESS, WALLET_PRIVATE_KEY, SEPOLIA_RPC_URL

logger = logging.getLogger("signer_service.signer")

SEPOLIA_CHAIN_ID = 11155111


@dataclass
class SignedResult:
    tx_hash: str        # 0x-prefixed 32-byte hex
    raw_tx: str         # 0x-prefixed RLP-encoded signed tx
    from_address: str
    to_address: str
    value_wei: str
    nonce: int


async def sign_transaction(
    to: str,
    value_wei: str,
    data: str = "0x",
    gas_limit: int = 21_000,
) -> SignedResult:
    """
    Build, sign, and broadcast a Sepolia EIP-1559 transaction.

    After signing locally, the raw transaction is submitted to the network
    via ``eth_sendRawTransaction``.  The returned ``tx_hash`` is the real
    on-chain transaction hash.
    """
    if not WALLET_PRIVATE_KEY:
        raise RuntimeError("WALLET_PRIV_KEY_2 is not set in environment")

    w3 = AsyncWeb3(AsyncWeb3.AsyncHTTPProvider(SEPOLIA_RPC_URL))

    from_addr = Web3.to_checksum_address(WALLET_ADDRESS)
    to_addr = Web3.to_checksum_address(to)

    # Fetch on-chain state
    nonce = await w3.eth.get_transaction_count(from_addr, "pending")
    latest = await w3.eth.get_block("latest")
    base_fee = latest.get("baseFeePerGas", 1_000_000_000)
    priority_fee = await w3.eth.max_priority_fee

    max_fee = 2 * base_fee + priority_fee

    tx = {
        "type": 2,  # EIP-1559
        "chainId": SEPOLIA_CHAIN_ID,
        "nonce": nonce,
        "to": to_addr,
        "value": int(value_wei),
        "gas": gas_limit,
        "maxFeePerGas": max_fee,
        "maxPriorityFeePerGas": priority_fee,
        "data": bytes.fromhex(data[2:]) if data.startswith("0x") and len(data) > 2 else b"",
    }

    signed = Account.sign_transaction(tx, WALLET_PRIVATE_KEY)

    raw_tx_hex = (
        signed.raw_transaction.hex()
        if isinstance(signed.raw_transaction, bytes)
        else signed.raw_transaction
    )
    raw_tx_bytes = (
        signed.raw_transaction
        if isinstance(signed.raw_transaction, bytes)
        else bytes.fromhex(signed.raw_transaction.removeprefix("0x"))
    )

    # ── Broadcast to the network ─────────────────────────────────────────
    tx_hash_bytes = await w3.eth.send_raw_transaction(raw_tx_bytes)
    on_chain_hash = (
        tx_hash_bytes.hex()
        if isinstance(tx_hash_bytes, bytes)
        else str(tx_hash_bytes)
    )
    # Ensure 0x prefix
    if not on_chain_hash.startswith("0x"):
        on_chain_hash = "0x" + on_chain_hash

    logger.info(
        "Tx broadcast: hash=%s  from=%s  to=%s  value=%s  nonce=%d",
        on_chain_hash, from_addr, to_addr, value_wei, nonce,
    )

    return SignedResult(
        tx_hash=on_chain_hash,
        raw_tx=raw_tx_hex if raw_tx_hex.startswith("0x") else "0x" + raw_tx_hex,
        from_address=from_addr,
        to_address=to_addr,
        value_wei=value_wei,
        nonce=nonce,
    )

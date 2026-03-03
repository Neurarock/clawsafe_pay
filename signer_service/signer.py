"""
Core signing logic — multi-chain aware.

Resolves the chain from the ``chains`` registry, builds, signs and broadcasts
a transaction using the appropriate chain provider and signer.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from signer_service.config import WALLET_ADDRESS, WALLET_PRIVATE_KEY

logger = logging.getLogger("signer_service.signer")


@dataclass
class SignedResult:
    tx_hash: str        # 0x-prefixed (or base58 for non-EVM)
    raw_tx: str         # hex-encoded signed tx
    from_address: str
    to_address: str
    value_wei: str
    nonce: int
    chain: str


async def sign_transaction(
    to: str,
    value_wei: str,
    data: str = "0x",
    gas_limit: int = 21_000,
    chain: str = "sepolia",
) -> SignedResult:
    """
    Build, sign, and broadcast a transaction on the specified chain.

    Uses the ``chains`` registry to resolve the correct provider, builder,
    and signer for the target chain. Falls back to the legacy Sepolia-only
    code path if the chain is ``sepolia`` and registry resolution fails.
    """
    if not WALLET_PRIVATE_KEY:
        raise RuntimeError("WALLET_PRIVATE_KEY is not set in environment")

    # Resolve chain implementation from registry
    from chains import get_chain
    reg = get_chain(chain)
    cfg = reg.config

    rpc_url = cfg.default_rpc_url
    if not rpc_url:
        raise RuntimeError(f"No RPC URL configured for chain {chain!r}")

    # Instantiate provider and broadcast
    provider = reg.provider_cls(rpc_url)
    signer = reg.signer_cls()

    from web3 import Web3
    from_addr = Web3.to_checksum_address(WALLET_ADDRESS)
    to_addr = Web3.to_checksum_address(to)

    # Fetch on-chain state via the chain provider
    nonce = await provider.get_nonce(from_addr)
    fees = await provider.get_fee_estimate()

    base_fee = fees.get("base_fee_wei", 1_000_000_000)
    priority_fee = fees.get("priority_fee_wei", 1_500_000_000)
    max_fee = 2 * base_fee + priority_fee

    evm_chain_id = cfg.extra.get("evm_chain_id", 11155111)

    # Build UnsignedTx payload
    from chains.base import UnsignedTx
    import hashlib

    tx_dict = {
        "type": "eip1559",
        "chain_id": evm_chain_id,
        "nonce": nonce,
        "gas_limit": gas_limit,
        "max_fee_per_gas": str(max_fee),
        "max_priority_fee_per_gas": str(priority_fee),
        "to": to_addr,
        "value": value_wei,
        "data": data,
    }
    digest_str = f"{evm_chain_id}:{nonce}:{to_addr}:{value_wei}:{gas_limit}"
    digest = hashlib.sha256(digest_str.encode()).digest()

    unsigned = UnsignedTx(
        chain_id=chain,
        intent_id="",
        from_address=from_addr,
        to_address=to_addr,
        value_raw=value_wei,
        digest=digest,
        payload=tx_dict,
    )

    # Sign
    signed_tx = await signer.sign(unsigned, WALLET_PRIVATE_KEY)

    # Broadcast via the chain provider
    on_chain_hash = await provider.broadcast(signed_tx.raw_tx)

    if not on_chain_hash.startswith("0x"):
        on_chain_hash = "0x" + on_chain_hash

    raw_tx_hex = signed_tx.raw_tx.hex() if isinstance(signed_tx.raw_tx, bytes) else str(signed_tx.raw_tx)
    if not raw_tx_hex.startswith("0x"):
        raw_tx_hex = "0x" + raw_tx_hex

    logger.info(
        "Tx broadcast on %s: hash=%s  from=%s  to=%s  value=%s  nonce=%d",
        cfg.display_name, on_chain_hash, from_addr, to_addr, value_wei, nonce,
    )

    return SignedResult(
        tx_hash=on_chain_hash,
        raw_tx=raw_tx_hex,
        from_address=from_addr,
        to_address=to_addr,
        value_wei=value_wei,
        nonce=nonce,
        chain=chain,
    )

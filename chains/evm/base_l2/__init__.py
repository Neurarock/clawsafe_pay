"""
chains.evm.base_l2 — Base L2 (Coinbase) chain registration.

**Status: placeholder** — registers the chain config but uses the shared
EVM provider/builder/signer.  To activate, set ``BASE_RPC_URL`` in ``.env``
and add Base chain ID (8453 mainnet / 84532 testnet) to the policy allowlist.
"""

import re

from chains.base import ChainConfig
from chains.registry import register_chain
from chains.evm.provider import EVMProvider
from chains.evm.builder import EVMTxBuilder
from chains.evm.signer import EVMTxSigner

BASE_SEPOLIA_CHAIN_ID = 84532  # Base Sepolia testnet
BASE_MAINNET_CHAIN_ID = 8453

config = ChainConfig(
    chain_id="base",
    display_name="Base Sepolia Testnet",
    chain_family="evm",
    native_asset="ETH",
    address_regex=re.compile(r"^0x[0-9a-fA-F]{40}$"),
    explorer_tx_url="https://sepolia.basescan.org/tx/{tx_hash}",
    explorer_addr_url="https://sepolia.basescan.org/address/{address}",
    default_rpc_url="https://sepolia.base.org",
    is_testnet=True,
    decimals=18,
    extra={"evm_chain_id": BASE_SEPOLIA_CHAIN_ID},
)

register_chain(
    config=config,
    provider_cls=EVMProvider,
    builder_cls=EVMTxBuilder,
    signer_cls=EVMTxSigner,
)

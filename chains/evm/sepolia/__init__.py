"""
chains.evm.sepolia — Sepolia testnet implementation (fully functional).

Auto-registers on import.
"""

import re

from chains.base import ChainConfig
from chains.registry import register_chain
from chains.evm.provider import EVMProvider
from chains.evm.builder import EVMTxBuilder
from chains.evm.signer import EVMTxSigner

SEPOLIA_CHAIN_ID = 11155111

config = ChainConfig(
    chain_id="sepolia",
    display_name="Sepolia Testnet",
    chain_family="evm",
    native_asset="ETH",
    address_regex=re.compile(r"^0x[0-9a-fA-F]{40}$"),
    explorer_tx_url="https://sepolia.etherscan.io/tx/{tx_hash}",
    explorer_addr_url="https://sepolia.etherscan.io/address/{address}",
    default_rpc_url="https://ethereum-sepolia-rpc.publicnode.com",
    is_testnet=True,
    decimals=18,
    extra={"evm_chain_id": SEPOLIA_CHAIN_ID},
)

register_chain(
    config=config,
    provider_cls=EVMProvider,
    builder_cls=EVMTxBuilder,
    signer_cls=EVMTxSigner,
)

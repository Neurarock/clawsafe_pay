"""
Solana chain configuration.

**Status: placeholder** — not registered in the chain registry until
provider, builder, and signer are implemented.
"""

import re
from chains.base import ChainConfig

SOLANA_DEVNET_CONFIG = ChainConfig(
    chain_id="solana-devnet",
    display_name="Solana Devnet",
    chain_family="solana",
    native_asset="SOL",
    address_regex=re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$"),  # base58
    explorer_tx_url="https://explorer.solana.com/tx/{tx_hash}?cluster=devnet",
    explorer_addr_url="https://explorer.solana.com/address/{address}?cluster=devnet",
    default_rpc_url="https://api.devnet.solana.com",
    is_testnet=True,
    decimals=9,
    extra={"cluster": "devnet"},
)

SOLANA_MAINNET_CONFIG = ChainConfig(
    chain_id="solana",
    display_name="Solana Mainnet",
    chain_family="solana",
    native_asset="SOL",
    address_regex=re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$"),
    explorer_tx_url="https://explorer.solana.com/tx/{tx_hash}",
    explorer_addr_url="https://explorer.solana.com/address/{address}",
    default_rpc_url="https://api.mainnet-beta.solana.com",
    is_testnet=False,
    decimals=9,
    extra={"cluster": "mainnet-beta"},
)

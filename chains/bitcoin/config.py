"""
Bitcoin chain configuration.

**Status: placeholder** — not registered in the chain registry until
provider, builder, and signer are implemented.
"""

import re
from chains.base import ChainConfig

BITCOIN_TESTNET_CONFIG = ChainConfig(
    chain_id="bitcoin-testnet",
    display_name="Bitcoin Testnet",
    chain_family="utxo",
    native_asset="BTC",
    # Testnet addresses: m/n (P2PKH), 2 (P2SH), tb1 (bech32)
    address_regex=re.compile(r"^(m|n|2|tb1)[a-zA-HJ-NP-Z0-9]{25,62}$"),
    explorer_tx_url="https://mempool.space/testnet/tx/{tx_hash}",
    explorer_addr_url="https://mempool.space/testnet/address/{address}",
    default_rpc_url=None,  # requires local node or third-party API
    is_testnet=True,
    decimals=8,
    extra={"network": "testnet"},
)

BITCOIN_MAINNET_CONFIG = ChainConfig(
    chain_id="bitcoin",
    display_name="Bitcoin Mainnet",
    chain_family="utxo",
    native_asset="BTC",
    # Mainnet: 1 (P2PKH), 3 (P2SH), bc1 (bech32/bech32m)
    address_regex=re.compile(r"^(1|3|bc1)[a-zA-HJ-NP-Z0-9]{25,62}$"),
    explorer_tx_url="https://mempool.space/tx/{tx_hash}",
    explorer_addr_url="https://mempool.space/address/{address}",
    default_rpc_url=None,
    is_testnet=False,
    decimals=8,
    extra={"network": "mainnet"},
)

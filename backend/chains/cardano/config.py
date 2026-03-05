"""
Cardano chain configuration.

**Status: placeholder**
"""

import re
from chains.base import ChainConfig

CARDANO_PREPROD_CONFIG = ChainConfig(
    chain_id="cardano-preprod",
    display_name="Cardano Pre-Production Testnet",
    chain_family="cardano",
    native_asset="ADA",
    address_regex=re.compile(r"^addr_test1[a-z0-9]{50,120}$"),
    explorer_tx_url="https://preprod.cardanoscan.io/transaction/{tx_hash}",
    explorer_addr_url="https://preprod.cardanoscan.io/address/{address}",
    default_rpc_url=None,  # typically uses Blockfrost or Ogmios
    is_testnet=True,
    decimals=6,
    extra={"network": "preprod", "network_magic": 1},
)

CARDANO_MAINNET_CONFIG = ChainConfig(
    chain_id="cardano",
    display_name="Cardano Mainnet",
    chain_family="cardano",
    native_asset="ADA",
    address_regex=re.compile(r"^addr1[a-z0-9]{50,120}$"),
    explorer_tx_url="https://cardanoscan.io/transaction/{tx_hash}",
    explorer_addr_url="https://cardanoscan.io/address/{address}",
    default_rpc_url=None,
    is_testnet=False,
    decimals=6,
    extra={"network": "mainnet", "network_magic": 764824073},
)

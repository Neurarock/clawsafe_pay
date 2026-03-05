"""
Zcash chain configuration.

**Status: placeholder**
"""

import re
from chains.base import ChainConfig

ZCASH_TESTNET_CONFIG = ChainConfig(
    chain_id="zcash-testnet",
    display_name="Zcash Testnet",
    chain_family="utxo",
    native_asset="ZEC",
    # t-addrs: tm/t2 (testnet), z-addrs: ztestsapling
    address_regex=re.compile(r"^(tm|t2|ztestsapling)[a-zA-Z0-9]{20,100}$"),
    explorer_tx_url="https://explorer.testnet.z.cash/tx/{tx_hash}",
    explorer_addr_url="https://explorer.testnet.z.cash/address/{address}",
    default_rpc_url=None,
    is_testnet=True,
    decimals=8,
    extra={"network": "testnet", "sapling": True},
)

ZCASH_MAINNET_CONFIG = ChainConfig(
    chain_id="zcash",
    display_name="Zcash Mainnet",
    chain_family="utxo",
    native_asset="ZEC",
    # t-addrs: t1/t3, z-addrs: zs (sapling), u (unified)
    address_regex=re.compile(r"^(t1|t3|zs|u1)[a-zA-Z0-9]{20,200}$"),
    explorer_tx_url="https://explorer.zcha.in/transactions/{tx_hash}",
    explorer_addr_url="https://explorer.zcha.in/accounts/{address}",
    default_rpc_url=None,
    is_testnet=False,
    decimals=8,
    extra={"network": "mainnet", "sapling": True},
)

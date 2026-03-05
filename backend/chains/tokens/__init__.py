"""
chains.tokens — Cross-chain token registry.

Tokens like USDC and USDT exist on multiple chains with different
contract addresses and decimal precision.  This module provides a
unified lookup so the pipeline can resolve a (chain, asset) pair to
the correct contract address and transfer method.

Usage::

    from chains.tokens import get_token

    usdc = get_token("sepolia", "USDC")
    print(usdc.contract_address)  # 0x...
    print(usdc.decimals)          # 6
"""

from chains.tokens.registry import (     # noqa: F401 – re-exported
    TokenConfig,
    get_token,
    list_tokens,
    register_token,
)

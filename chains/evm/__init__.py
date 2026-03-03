"""
chains.evm — EVM chain family (Ethereum, L2 rollups, testnets).

Shared provider, builder, and signer classes that work with any
EIP-1559-compatible chain.  Chain-specific differences (chain ID,
RPC URL, explorer) are captured in ``ChainConfig.extra``.
"""

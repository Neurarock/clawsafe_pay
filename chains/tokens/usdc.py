"""
USDC token deployments across chains.

Sources:
  - https://developers.circle.com/stablecoins/docs/usdc-on-test-networks
  - https://www.circle.com/en/multi-chain-usdc

NOTE: Testnet contract addresses may change.  Verify before production use.
"""

from chains.tokens.registry import TokenConfig, register_token

# ── EVM chains ───────────────────────────────────────────────────────────────

USDC_SEPOLIA = TokenConfig(
    symbol="USDC",
    name="USD Coin",
    chain_id="sepolia",
    contract_address="0x1c7D4B196Cb0C7B01d743Fbc6116a902379C7238",
    decimals=6,
    transfer_method="erc20",
    is_testnet=True,
    extra={"proxy": True},
)

USDC_BASE = TokenConfig(
    symbol="USDC",
    name="USD Coin",
    chain_id="base",
    contract_address="0x036CbD53842c5426634e7929541eC2318f3dCF7e",  # Base Sepolia
    decimals=6,
    transfer_method="erc20",
    is_testnet=True,
    extra={"proxy": True},
)

# ── Solana ───────────────────────────────────────────────────────────────────

USDC_SOLANA_DEVNET = TokenConfig(
    symbol="USDC",
    name="USD Coin",
    chain_id="solana-devnet",
    contract_address="4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU",  # devnet mint
    decimals=6,
    transfer_method="spl",
    is_testnet=True,
)

# ── Cardano ──────────────────────────────────────────────────────────────────
# USDC on Cardano is not yet widely available as a native token.
# Placeholder for future bridge/integration.

# ── Register all ─────────────────────────────────────────────────────────────

for _cfg in (USDC_SEPOLIA, USDC_BASE, USDC_SOLANA_DEVNET):
    register_token(_cfg)

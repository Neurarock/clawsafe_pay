"""
USDT (Tether) token deployments across chains.

Sources:
  - https://tether.to/en/supported-protocols/
  - Contract addresses from chain-specific block explorers

NOTE: Testnet contract addresses may change.  Verify before production use.
"""

from chains.tokens.registry import TokenConfig, register_token

# ── EVM chains ───────────────────────────────────────────────────────────────

USDT_SEPOLIA = TokenConfig(
    symbol="USDT",
    name="Tether USD",
    chain_id="sepolia",
    contract_address="0x7169D38820dfd117C3FA1f22a697dBA58d90BA06",  # Sepolia testnet
    decimals=6,
    transfer_method="erc20",
    is_testnet=True,
)

USDT_BASE = TokenConfig(
    symbol="USDT",
    name="Tether USD",
    chain_id="base",
    contract_address="0x0000000000000000000000000000000000000000",  # placeholder
    decimals=6,
    transfer_method="erc20",
    is_testnet=True,
    extra={"note": "Verify contract address before use"},
)

# ── Solana ───────────────────────────────────────────────────────────────────

USDT_SOLANA_DEVNET = TokenConfig(
    symbol="USDT",
    name="Tether USD",
    chain_id="solana-devnet",
    contract_address="Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",  # mainnet mint; devnet may differ
    decimals=6,
    transfer_method="spl",
    is_testnet=True,
    extra={"note": "Verify devnet mint address"},
)

# ── Register all ─────────────────────────────────────────────────────────────

for _cfg in (USDT_SEPOLIA, USDT_BASE, USDT_SOLANA_DEVNET):
    register_token(_cfg)

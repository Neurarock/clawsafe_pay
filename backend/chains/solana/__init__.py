"""
chains.solana — Solana chain support.

**Status: placeholder** — stubs only.  Implement ``SolanaProvider``,
``SolanaTxBuilder``, and ``SolanaTxSigner`` to activate.

Dependencies (not yet installed):
    pip install solders solana

Key differences from EVM:
    - Account model (not UTXO), but uses 64-byte Ed25519 signatures
    - Addresses are base58-encoded 32-byte public keys
    - Transactions use "instructions" instead of a single call
    - Fees are per-signature (lamports), not per-gas
    - Native asset: SOL (9 decimals)
    - Token transfers use SPL Token program
"""

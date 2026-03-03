"""
chains.cardano — Cardano chain support.

**Status: placeholder** — stubs only.

Dependencies (not yet installed):
    pip install pycardano  # or cardano-python

Key differences from EVM:
    - Extended UTXO model (eUTxO) with on-chain datums
    - Addresses: Bech32-encoded (addr1… for mainnet, addr_test1… for testnet)
    - Fees: calculated deterministically from tx size + script execution units
    - Native asset: ADA (6 decimals, 1 ADA = 1_000_000 lovelace)
    - Multi-asset ledger: native tokens (no contract needed for fungible tokens)
    - Smart contracts: Plutus (Haskell-based) scripts
    - Signing: Ed25519
"""

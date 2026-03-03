"""
chains.bitcoin — Bitcoin chain support.

**Status: placeholder** — stubs only.  Implement ``BitcoinProvider``,
``BitcoinTxBuilder``, and ``BitcoinTxSigner`` to activate.

Dependencies (not yet installed):
    pip install bitcoinlib  # or python-bitcoinrpc, bip-utils

Key differences from EVM:
    - UTXO model (not account-based)
    - Addresses: P2PKH (1…), P2SH (3…), Bech32 (bc1…), Bech32m (bc1p…)
    - Fees are sat/vByte (variable tx size)
    - Native asset: BTC (8 decimals, 1 BTC = 100_000_000 satoshi)
    - No smart contracts in the EVM sense; limited Script
    - Signing uses ECDSA secp256k1 (similar curve to Ethereum)
"""

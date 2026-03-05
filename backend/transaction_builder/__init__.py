"""
transaction_builder — deterministic EIP-1559 transaction construction for ClawSafe Pay.

Public API:
    build_draft_tx(intent, provider, from_address, policy) -> DraftTx
    Web3Provider(rpc_url) -> ProviderInterface
    PolicyConfig(...)
    PaymentIntent(...)
    DraftTx(...)
    PolicyError
    ProviderError
"""

from .builder import build_draft_tx
from .models import (
    CHAIN_FAMILY,
    DraftTx,
    PaymentIntent,
    PolicyConfig,
    PolicyError,
    ProviderError,
    SEPOLIA_CHAIN_ID,
    SUPPORTED_ASSETS,
    SUPPORTED_CHAINS,
)
from .provider import GasEstimate, ProviderInterface, Web3Provider

__all__ = [
    "build_draft_tx",
    "CHAIN_FAMILY",
    "DraftTx",
    "GasEstimate",
    "PaymentIntent",
    "PolicyConfig",
    "PolicyError",
    "ProviderError",
    "ProviderInterface",
    "SEPOLIA_CHAIN_ID",
    "SUPPORTED_ASSETS",
    "SUPPORTED_CHAINS",
    "Web3Provider",
]

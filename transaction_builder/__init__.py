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
    DraftTx,
    PaymentIntent,
    PolicyConfig,
    PolicyError,
    ProviderError,
    SEPOLIA_CHAIN_ID,
)
from .provider import GasEstimate, ProviderInterface, Web3Provider

__all__ = [
    "build_draft_tx",
    "DraftTx",
    "GasEstimate",
    "PaymentIntent",
    "PolicyConfig",
    "PolicyError",
    "ProviderError",
    "ProviderInterface",
    "SEPOLIA_CHAIN_ID",
    "Web3Provider",
]

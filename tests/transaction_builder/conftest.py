"""
Shared fixtures and helpers for transaction_builder tests.
"""

import pytest
from datetime import datetime, timezone

from transaction_builder.models import PaymentIntent, PolicyConfig
from transaction_builder.provider import GasEstimate, ProviderInterface


# ── Addresses ────────────────────────────────────────────────────────────────

FROM_ADDRESS = "0x742d35cc6634c0532925a3b8d4c9d5a3aa5a3eb"
VALID_RECIPIENT = "0xd8da6bf26964af9d7eed9e03e53415d37aa96045"
OTHER_ADDRESS = "0x1111111111111111111111111111111111111111"

# ── Mock provider ─────────────────────────────────────────────────────────────


class MockProvider(ProviderInterface):
    """In-memory provider — no network calls."""

    def __init__(
        self,
        nonce: int = 5,
        base_fee_wei: int = 10_000_000_000,   # 10 gwei
        priority_fee_wei: int = 1_000_000_000,  # 1 gwei
    ) -> None:
        self._nonce = nonce
        self._base_fee = base_fee_wei
        self._priority_fee = priority_fee_wei

    async def get_nonce(self, address: str) -> int:
        return self._nonce

    async def get_gas_estimate(self) -> GasEstimate:
        return GasEstimate(
            base_fee_wei=self._base_fee,
            max_priority_fee_wei=self._priority_fee,
        )


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_provider() -> MockProvider:
    return MockProvider()


@pytest.fixture
def policy() -> PolicyConfig:
    return PolicyConfig(recipient_allowlist=[VALID_RECIPIENT])


@pytest.fixture
def valid_intent() -> PaymentIntent:
    return PaymentIntent(
        intent_id="test-intent-001",
        from_user="userA",
        to_user="userB",
        amount_wei="10000000000000000",  # 0.01 ETH
        to_address=VALID_RECIPIENT,
        created_at=datetime.now(timezone.utc),
    )

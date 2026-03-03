"""
Unit tests for the EIP-1559 transaction builder (transaction_builder/builder.py).

Provider is mocked — no network calls.
"""

import pytest
from datetime import datetime, timezone

from transaction_builder.builder import build_draft_tx
from transaction_builder.models import PaymentIntent, PolicyConfig, PolicyError, ProviderError
from transaction_builder.provider import GasEstimate, ProviderInterface

from .conftest import FROM_ADDRESS, MockProvider, VALID_RECIPIENT, OTHER_ADDRESS


# ── Helpers ───────────────────────────────────────────────────────────────────


def make_intent(**overrides) -> PaymentIntent:
    defaults = dict(
        intent_id="build-test-001",
        from_user="userA",
        to_user="userB",
        amount_wei="10000000000000000",  # 0.01 ETH
        to_address=VALID_RECIPIENT,
        created_at=datetime.now(timezone.utc),
    )
    defaults.update(overrides)
    return PaymentIntent(**defaults)


def default_policy() -> PolicyConfig:
    return PolicyConfig(recipient_allowlist=[VALID_RECIPIENT])


# ── Core fields ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_returned_fields_match_intent():
    draft = await build_draft_tx(make_intent(), MockProvider(), FROM_ADDRESS, default_policy())

    assert draft.intent_id == "build-test-001"
    assert draft.chain_id == 11155111
    assert draft.to == VALID_RECIPIENT
    assert draft.value_wei == "10000000000000000"
    assert draft.data == "0x"
    assert draft.tx_type == "eip1559"


@pytest.mark.asyncio
async def test_nonce_comes_from_provider():
    draft = await build_draft_tx(make_intent(), MockProvider(nonce=42), FROM_ADDRESS, default_policy())
    assert draft.nonce == 42


@pytest.mark.asyncio
async def test_gas_limit_is_21000_for_native_transfer():
    draft = await build_draft_tx(make_intent(), MockProvider(), FROM_ADDRESS, default_policy())
    assert draft.gas_limit == 21_000


@pytest.mark.asyncio
async def test_from_address_stored_lowercase():
    draft = await build_draft_tx(
        make_intent(), MockProvider(), "0xABC123" + "0" * 34, default_policy()
    )
    assert draft.from_address == draft.from_address.lower()


# ── Digest properties ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_digest_is_0x_prefixed_32_byte_hex():
    draft = await build_draft_tx(make_intent(), MockProvider(), FROM_ADDRESS, default_policy())

    assert draft.digest.startswith("0x"), "digest must be 0x-prefixed"
    assert len(draft.digest) == 66, "digest must be 0x + 64 hex chars (32 bytes)"
    # Validate it's actually hex
    bytes.fromhex(draft.digest[2:])


@pytest.mark.asyncio
async def test_digest_is_deterministic_given_same_inputs():
    """Same intent + same provider state → identical digest."""
    intent = make_intent(intent_id="determinism-check")
    p1 = MockProvider(nonce=7, base_fee_wei=10_000_000_000, priority_fee_wei=1_000_000_000)
    p2 = MockProvider(nonce=7, base_fee_wei=10_000_000_000, priority_fee_wei=1_000_000_000)

    d1 = await build_draft_tx(intent, p1, FROM_ADDRESS, default_policy())
    d2 = await build_draft_tx(intent, p2, FROM_ADDRESS, default_policy())
    assert d1.digest == d2.digest


@pytest.mark.asyncio
async def test_digest_changes_when_nonce_changes():
    intent = make_intent()
    d1 = await build_draft_tx(intent, MockProvider(nonce=1), FROM_ADDRESS, default_policy())
    d2 = await build_draft_tx(intent, MockProvider(nonce=2), FROM_ADDRESS, default_policy())
    assert d1.digest != d2.digest


@pytest.mark.asyncio
async def test_digest_changes_when_value_changes():
    p = MockProvider(nonce=1)
    d1 = await build_draft_tx(make_intent(amount_wei="10000000000000000"), p, FROM_ADDRESS, default_policy())

    # Fresh provider with same nonce
    p2 = MockProvider(nonce=1)
    d2 = await build_draft_tx(make_intent(amount_wei="20000000000000000"), p2, FROM_ADDRESS, default_policy())
    assert d1.digest != d2.digest


@pytest.mark.asyncio
async def test_digest_changes_when_recipient_changes():
    policy = PolicyConfig(recipient_allowlist=["*"])
    p1 = MockProvider(nonce=1)
    p2 = MockProvider(nonce=1)
    d1 = await build_draft_tx(make_intent(to_address=VALID_RECIPIENT), p1, FROM_ADDRESS, policy)
    d2 = await build_draft_tx(make_intent(to_address=OTHER_ADDRESS), p2, FROM_ADDRESS, policy)
    assert d1.digest != d2.digest


# ── Expiry ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_expires_at_is_roughly_2_minutes_from_now():
    from datetime import timedelta

    before = datetime.now(timezone.utc)
    draft = await build_draft_tx(make_intent(), MockProvider(), FROM_ADDRESS, default_policy())
    after = datetime.now(timezone.utc)

    window_seconds = 120
    tolerance = 5

    assert draft.expires_at > before + timedelta(seconds=window_seconds - tolerance)
    assert draft.expires_at < after + timedelta(seconds=window_seconds + tolerance)


# ── Fee calculation ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_max_fee_does_not_exceed_policy_multiplier_cap():
    """max_fee_per_gas <= 2× base_fee + tip at all times."""
    base_fee = 50_000_000_000   # 50 gwei
    tip_cap = 2_000_000_000     # 2 gwei policy cap
    policy = PolicyConfig(
        recipient_allowlist=[VALID_RECIPIENT],
        max_fee_per_gas_multiplier=2.0,
        tip_wei=tip_cap,
    )
    provider = MockProvider(base_fee_wei=base_fee, priority_fee_wei=10_000_000_000)

    draft = await build_draft_tx(make_intent(), provider, FROM_ADDRESS, policy)

    expected_cap = int(2.0 * base_fee) + tip_cap
    assert int(draft.max_fee_per_gas) <= expected_cap


@pytest.mark.asyncio
async def test_tip_is_capped_by_policy():
    """Node suggestion of 10 gwei tip should be capped to policy.tip_wei."""
    policy = PolicyConfig(
        recipient_allowlist=[VALID_RECIPIENT],
        tip_wei=1_000_000_000,  # 1 gwei cap
    )
    provider = MockProvider(priority_fee_wei=10_000_000_000)  # 10 gwei suggested

    draft = await build_draft_tx(make_intent(), provider, FROM_ADDRESS, policy)
    assert int(draft.max_priority_fee_per_gas) <= 1_000_000_000


# ── Policy violations ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_amount_over_cap_raises_policy_error():
    intent = make_intent(amount_wei="1100000000000000000")  # 1.1 ETH > 1 ETH default cap
    with pytest.raises(PolicyError, match="exceeds cap"):
        await build_draft_tx(intent, MockProvider(), FROM_ADDRESS, default_policy())


@pytest.mark.asyncio
async def test_unlisted_recipient_raises_policy_error():
    intent = make_intent(to_address=OTHER_ADDRESS)
    with pytest.raises(PolicyError, match="allowlist"):
        await build_draft_tx(intent, MockProvider(), FROM_ADDRESS, default_policy())


@pytest.mark.asyncio
async def test_none_policy_uses_safe_defaults():
    """Passing policy=None should still work with conservative defaults."""
    # Default policy has empty allowlist → should raise unless we add VALID_RECIPIENT
    # So this test confirms None policy uses PolicyConfig() defaults (empty allowlist blocks)
    intent = make_intent()
    with pytest.raises(PolicyError, match="allowlist is empty"):
        await build_draft_tx(intent, MockProvider(), FROM_ADDRESS, policy=None)


# ── Provider errors ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_nonce_provider_error_propagates():
    class FailingNonceProvider(MockProvider):
        async def get_nonce(self, address: str) -> int:
            raise ProviderError("connection refused")

    with pytest.raises(ProviderError, match="connection refused"):
        await build_draft_tx(make_intent(), FailingNonceProvider(), FROM_ADDRESS, default_policy())


@pytest.mark.asyncio
async def test_gas_provider_error_propagates():
    class FailingGasProvider(MockProvider):
        async def get_gas_estimate(self) -> GasEstimate:
            raise ProviderError("RPC timeout")

    with pytest.raises(ProviderError, match="RPC timeout"):
        await build_draft_tx(make_intent(), FailingGasProvider(), FROM_ADDRESS, default_policy())


# ── Input model validation ────────────────────────────────────────────────────


def test_payment_intent_rejects_invalid_address():
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="Invalid EVM address"):
        make_intent(to_address="not-an-address")


def test_payment_intent_rejects_non_integer_amount():
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="decimal integer"):
        make_intent(amount_wei="0.01")


def test_payment_intent_rejects_zero_amount():
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="positive"):
        make_intent(amount_wei="0")


def test_payment_intent_rejects_unsupported_chain():
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="Unsupported chain"):
        make_intent(chain="mainnet")


def test_payment_intent_normalises_address_to_lowercase():
    intent = make_intent(to_address="0xD8DA6BF26964AF9D7EED9E03E53415D37AA96045")
    assert intent.to_address == VALID_RECIPIENT  # all lowercase

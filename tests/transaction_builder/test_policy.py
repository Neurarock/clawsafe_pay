"""
Unit tests for the policy engine (transaction_builder/policy.py).

All tests are synchronous — no I/O, no network.
"""

import pytest
from datetime import datetime, timezone, timedelta

from transaction_builder.models import PolicyConfig, PolicyError, DraftTx
from transaction_builder.policy import validate_intent, validate_draft_tx

from .conftest import VALID_RECIPIENT, OTHER_ADDRESS, FROM_ADDRESS


# ── Helpers ───────────────────────────────────────────────────────────────────


def make_intent(**overrides):
    from transaction_builder.models import PaymentIntent

    defaults = dict(
        intent_id="pol-test-001",
        from_user="userA",
        to_user="userB",
        amount_wei="10000000000000000",  # 0.01 ETH
        to_address=VALID_RECIPIENT,
        created_at=datetime.now(timezone.utc),
    )
    defaults.update(overrides)
    return PaymentIntent(**defaults)


def make_policy(**overrides) -> PolicyConfig:
    defaults = dict(recipient_allowlist=[VALID_RECIPIENT])
    defaults.update(overrides)
    return PolicyConfig(**defaults)


def make_draft(**overrides) -> DraftTx:
    defaults = dict(
        intent_id="pol-test-001",
        from_address=FROM_ADDRESS,
        to=VALID_RECIPIENT,
        value_wei="10000000000000000",
        nonce=5,
        gas_limit=21_000,
        max_fee_per_gas="21000000000",        # 21 gwei (within 2× of 10 gwei base + 1 tip)
        max_priority_fee_per_gas="1000000000",  # 1 gwei
        digest="0x" + "ab" * 32,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=2),
    )
    defaults.update(overrides)
    return DraftTx(**defaults)


BASE_FEE_10_GWEI = 10_000_000_000


# ── validate_intent ───────────────────────────────────────────────────────────


class TestValidateIntent:
    def test_valid_intent_passes(self):
        validate_intent(make_intent(), make_policy())

    # ── Amount cap ────────────────────────────────────────────────────────────

    def test_amount_over_cap_raises(self):
        intent = make_intent(amount_wei="1100000000000000000")  # 1.1 ETH > 1 ETH cap
        with pytest.raises(PolicyError, match="exceeds cap"):
            validate_intent(intent, make_policy())

    def test_amount_exactly_at_cap_passes(self):
        intent = make_intent(amount_wei="1000000000000000000")  # exactly 1 ETH
        validate_intent(intent, make_policy())

    def test_amount_one_wei_over_cap_raises(self):
        intent = make_intent(amount_wei="1000000000000000001")
        with pytest.raises(PolicyError, match="exceeds cap"):
            validate_intent(intent, make_policy())

    def test_custom_cap_respected(self):
        policy = make_policy(max_amount_wei=1_000_000_000_000_000)  # 0.001 ETH cap
        intent = make_intent(amount_wei="2000000000000000")  # 0.002 ETH
        with pytest.raises(PolicyError, match="exceeds cap"):
            validate_intent(intent, policy)

    # ── Recipient allowlist ───────────────────────────────────────────────────

    def test_unlisted_recipient_blocked(self):
        intent = make_intent(to_address=OTHER_ADDRESS)
        with pytest.raises(PolicyError, match="not in the allowlist"):
            validate_intent(intent, make_policy())

    def test_allowlisted_recipient_passes(self):
        validate_intent(make_intent(to_address=VALID_RECIPIENT), make_policy())

    def test_wildcard_allowlist_permits_any_address(self):
        intent = make_intent(to_address=OTHER_ADDRESS)
        policy = make_policy(recipient_allowlist=["*"])
        validate_intent(intent, policy)  # should not raise

    def test_empty_allowlist_blocks_everything(self):
        with pytest.raises(PolicyError, match="allowlist is empty"):
            validate_intent(make_intent(), make_policy(recipient_allowlist=[]))

    def test_allowlist_matching_is_case_insensitive(self):
        # Intent address is uppercase, allowlist is lowercase
        intent = make_intent(to_address="0xD8DA6BF26964AF9D7EED9E03E53415D37AA96045")
        validate_intent(intent, make_policy())  # allowlist has lowercase version

    def test_multiple_addresses_in_allowlist(self):
        policy = make_policy(recipient_allowlist=[VALID_RECIPIENT, OTHER_ADDRESS])
        validate_intent(make_intent(to_address=OTHER_ADDRESS), policy)


# ── validate_draft_tx ─────────────────────────────────────────────────────────


class TestValidateDraftTx:
    def test_clean_draft_returns_no_warnings(self):
        # max_fee=21 gwei, base_fee=10 gwei, tip=1 gwei → 21 < 1.5*10+1=16? No, 21 > 16
        # Let's use a clearly below-warn fee: 12 gwei < 1.5*10+1=16 gwei
        draft = make_draft(
            max_fee_per_gas="12000000000",        # 12 gwei
            max_priority_fee_per_gas="1000000000",  # 1 gwei
        )
        warnings = validate_draft_tx(draft, make_policy(), BASE_FEE_10_GWEI)
        assert warnings == []

    # ── Calldata ──────────────────────────────────────────────────────────────

    def test_non_empty_calldata_raises(self):
        draft = make_draft(data="0xdeadbeef")
        with pytest.raises(PolicyError, match="calldata must be empty"):
            validate_draft_tx(draft, make_policy(), BASE_FEE_10_GWEI)

    def test_empty_string_data_passes(self):
        draft = make_draft(data="")
        validate_draft_tx(draft, make_policy(), BASE_FEE_10_GWEI)

    def test_zero_x_data_passes(self):
        draft = make_draft(data="0x")
        validate_draft_tx(draft, make_policy(), BASE_FEE_10_GWEI)

    # ── Gas limit ─────────────────────────────────────────────────────────────

    def test_gas_above_native_limit_raises(self):
        draft = make_draft(gas_limit=100_000)
        with pytest.raises(PolicyError, match="gas_limit"):
            validate_draft_tx(draft, make_policy(), BASE_FEE_10_GWEI)

    def test_gas_at_native_limit_passes(self):
        draft = make_draft(gas_limit=21_000)
        validate_draft_tx(draft, make_policy(), BASE_FEE_10_GWEI)

    # ── Fee cap ───────────────────────────────────────────────────────────────

    def test_max_fee_over_2x_base_raises(self):
        # cap = 2 * 10 gwei + 1 gwei tip = 21 gwei
        # 100 gwei > cap → PolicyError
        draft = make_draft(max_fee_per_gas="100000000000")  # 100 gwei
        with pytest.raises(PolicyError, match="exceeds hard cap"):
            validate_draft_tx(draft, make_policy(), BASE_FEE_10_GWEI)

    def test_max_fee_exactly_at_cap_passes(self):
        # cap = 2 * 10 + 1 = 21 gwei
        draft = make_draft(
            max_fee_per_gas="21000000000",
            max_priority_fee_per_gas="1000000000",
        )
        validate_draft_tx(draft, make_policy(), BASE_FEE_10_GWEI)

    def test_max_fee_one_wei_over_cap_raises(self):
        # cap = 2 * 10_000_000_000 + 1_000_000_000 = 21_000_000_000
        draft = make_draft(
            max_fee_per_gas="21000000001",
            max_priority_fee_per_gas="1000000000",
        )
        with pytest.raises(PolicyError, match="exceeds hard cap"):
            validate_draft_tx(draft, make_policy(), BASE_FEE_10_GWEI)

    # ── Soft warnings ─────────────────────────────────────────────────────────

    def test_fee_above_1_5x_base_generates_warning(self):
        # warn threshold = 1.5 * 10 gwei + 1 gwei tip = 16 gwei
        # cap = 2 * 10 + 1 = 21 gwei
        # 18 gwei is above warn, below cap → should warn
        draft = make_draft(
            max_fee_per_gas="18000000000",        # 18 gwei
            max_priority_fee_per_gas="1000000000",  # 1 gwei
        )
        warnings = validate_draft_tx(draft, make_policy(), BASE_FEE_10_GWEI)
        assert len(warnings) == 1
        assert "1.5x" in warnings[0] or "1.5×" in warnings[0]

    def test_fee_below_warn_threshold_no_warning(self):
        # 12 gwei < 1.5*10+1=16 gwei → no warning
        draft = make_draft(
            max_fee_per_gas="12000000000",
            max_priority_fee_per_gas="1000000000",
        )
        warnings = validate_draft_tx(draft, make_policy(), BASE_FEE_10_GWEI)
        assert warnings == []

    def test_high_base_fee_scales_thresholds(self):
        # base_fee = 100 gwei, tip = 1 gwei
        # hard cap = 2 * 100 + 1 = 201 gwei
        # warn threshold = 1.5 * 100 + 1 = 151 gwei
        base_fee = 100_000_000_000
        draft = make_draft(
            max_fee_per_gas="160000000000",       # 160 gwei: above warn, below cap
            max_priority_fee_per_gas="1000000000",
        )
        warnings = validate_draft_tx(draft, make_policy(), base_fee)
        assert len(warnings) == 1

    def test_returns_list_type_on_success(self):
        draft = make_draft(max_fee_per_gas="12000000000")
        result = validate_draft_tx(draft, make_policy(), BASE_FEE_10_GWEI)
        assert isinstance(result, list)

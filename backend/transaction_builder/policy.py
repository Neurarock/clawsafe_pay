"""
Policy engine for PaymentIntent and DraftTx validation.

All functions are pure (no I/O) — deterministic, side-effect-free, and easily testable.
"""

from .models import PaymentIntent, DraftTx, PolicyConfig, PolicyError

_CHAIN_NAME_TO_ID: dict[str, int] = {
    "sepolia": 11155111,
    "base": 84532,       # Base Sepolia testnet
}

# Soft-warning threshold as a fraction of the hard cap multiplier
_WARN_FEE_MULTIPLIER = 1.5


def validate_intent(intent: PaymentIntent, config: PolicyConfig) -> None:
    """
    Validate a PaymentIntent against policy.

    Raises PolicyError on any hard violation.
    Returns None on success.
    """
    # Chain
    chain_id = _CHAIN_NAME_TO_ID.get(intent.chain)
    if chain_id not in config.allowed_chain_ids:
        raise PolicyError(
            f"Chain {intent.chain!r} (id={chain_id}) is not in allowed list "
            f"{config.allowed_chain_ids}"
        )

    # Amount cap
    amount = int(intent.amount_wei)
    if amount > config.max_amount_wei:
        raise PolicyError(
            f"Amount {amount} wei exceeds cap {config.max_amount_wei} wei "
            f"({config.max_amount_wei / 1e18:.4f} ETH max)"
        )

    # Recipient allowlist
    if not config.recipient_allowlist:
        raise PolicyError(
            "Recipient allowlist is empty — all transfers are blocked. "
            "Add addresses or use ['*'] to allow any recipient."
        )
    normalized_allowlist = [a.lower() for a in config.recipient_allowlist]
    if "*" not in normalized_allowlist and intent.to_address.lower() not in normalized_allowlist:
        raise PolicyError(
            f"Recipient {intent.to_address!r} is not in the allowlist"
        )


def validate_draft_tx(
    draft: DraftTx,
    config: PolicyConfig,
    current_base_fee_wei: int,
) -> list[str]:
    """
    Validate a constructed DraftTx against policy given the current base fee.

    Returns a list of warning strings for soft violations (non-fatal).
    Raises PolicyError for hard violations.
    """
    warnings: list[str] = []

    # Gas limit: native transfers use 21k, contract calls use gas_limit_contract_call
    has_calldata = draft.data not in ("0x", "", b"")
    gas_cap = config.gas_limit_contract_call if has_calldata else config.gas_limit_native_transfer
    if draft.gas_limit > gas_cap:
        raise PolicyError(
            f"gas_limit {draft.gas_limit} exceeds maximum {gas_cap} "
            f"for {'contract calls' if has_calldata else 'native transfers'}"
        )

    # Fee hard cap: max_fee_per_gas <= multiplier * base_fee + tip
    max_fee = int(draft.max_fee_per_gas)
    tip = int(draft.max_priority_fee_per_gas)
    fee_cap = int(config.max_fee_per_gas_multiplier * current_base_fee_wei) + tip
    if max_fee > fee_cap:
        raise PolicyError(
            f"max_fee_per_gas {max_fee} wei exceeds hard cap {fee_cap} wei "
            f"({config.max_fee_per_gas_multiplier}× base_fee + tip)"
        )

    # Fee soft warning: max_fee > 1.5× base_fee + tip
    warn_threshold = int(_WARN_FEE_MULTIPLIER * current_base_fee_wei) + tip
    if max_fee > warn_threshold:
        warnings.append(
            f"max_fee_per_gas {max_fee} wei is more than "
            f"{_WARN_FEE_MULTIPLIER}× current base_fee ({current_base_fee_wei} wei) — "
            f"gas price is elevated"
        )

    return warnings

"""
EIP-1559 transaction builder.

Takes a PaymentIntent + on-chain state → produces a fully-specified, unsigned
DraftTx with a cryptographic signing digest.

Responsibilities:
  1. Validate intent against policy (pre-build)
  2. Fetch nonce + gas estimate from provider
  3. Apply fee caps from policy
  4. Compute the EIP-1559 signing hash (digest)
  5. Validate the resulting DraftTx (post-build)
  6. Return DraftTx

No signing or broadcasting happens here. This module is purely deterministic
given fixed provider responses.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta

from .models import (
    DraftTx,
    PaymentIntent,
    PolicyConfig,
    PolicyError,
    SEPOLIA_CHAIN_ID,
)
from .policy import validate_intent, validate_draft_tx
from .provider import ProviderInterface

__all__ = ["build_draft_tx"]

# Native ETH transfer always uses exactly 21,000 gas units
_GAS_LIMIT_NATIVE = 21_000

# Approval window: digest is valid for signing for this duration.
# Once expired the publisher must rebuild (new nonce + fresh gas snapshot) and
# re-present to the user.
#
# DeFi (future note): for time-sensitive transactions (DEX swaps, liquidations,
# deadline-bound contract calls) gas can move significantly within seconds.
# The right pattern is:
#   1. Detect staleness early — monitor mempool; if base_fee rises >X% above the
#      snapshot, proactively invalidate the current intent and rebuild.
#   2. Re-build produces a new DraftTx with a new digest (different nonce guard
#      or same nonce with higher fee), which the user must re-approve.
#   3. The publisher state machine needs a "rebuilding" transition from
#      "awaiting_approval" → "building" for this case.
#   4. For contracts with on-chain deadlines (e.g. Uniswap `deadline` param),
#      also re-validate that the deadline has not passed before re-submitting.
_APPROVAL_WINDOW_SECONDS = 120


def _compute_digest(
    chain_id: int,
    nonce: int,
    max_priority_fee_per_gas: int,
    max_fee_per_gas: int,
    gas_limit: int,
    to: str,
    value_wei: int,
    data: bytes = b"",
) -> str:
    """
    Compute the EIP-1559 signing hash for an unsigned transaction.

    Hash = keccak256(0x02 || rlp([
        chain_id, nonce, max_priority_fee_per_gas, max_fee_per_gas,
        gas_limit, to, value, data, access_list=[]
    ]))

    Returns a 0x-prefixed 32-byte hex string.

    Uses eth_account's TypedTransaction internals which are stable across
    eth-account >= 0.8.0 and are the same path taken by Account.sign_transaction().
    """
    try:
        from eth_account.typed_transactions import TypedTransaction
        from web3 import Web3
    except ImportError as exc:
        raise ImportError(
            "eth-account and web3 are required. "
            "Install them: pip install eth-account web3"
        ) from exc

    # TypedTransaction.from_dict requires a checksum address for 'to'
    to_checksummed = Web3.to_checksum_address(to)

    tx_dict = {
        "type": "0x2",
        "chainId": chain_id,
        "nonce": nonce,
        "maxPriorityFeePerGas": max_priority_fee_per_gas,
        "maxFeePerGas": max_fee_per_gas,
        "gas": gas_limit,
        "to": to_checksummed,
        "value": value_wei,
        "data": data,
        "accessList": [],
    }
    typed_tx = TypedTransaction.from_dict(tx_dict)
    digest_bytes: bytes = typed_tx.hash()
    return "0x" + digest_bytes.hex()


async def build_draft_tx(
    intent: PaymentIntent,
    provider: ProviderInterface,
    from_address: str,
    policy: PolicyConfig | None = None,
) -> DraftTx:
    """
    Build a fully-specified unsigned EIP-1559 draft transaction.

    Args:
        intent:       Validated PaymentIntent from the publisher agent.
        provider:     On-chain state source (real or mock).
        from_address: Signer wallet address (used for nonce lookup).
        policy:       Enforcement constraints. Uses conservative defaults if None.

    Returns:
        DraftTx with all fields populated and a cryptographic digest.

    Raises:
        PolicyError:   Intent or resulting tx violates a policy constraint.
        ProviderError: RPC call failed.
    """
    if policy is None:
        policy = PolicyConfig()

    # ── Step 1: Validate intent before hitting the network ──────────────────
    validate_intent(intent, policy)

    # ── Step 2: Fetch on-chain state ─────────────────────────────────────────
    nonce = await provider.get_nonce(from_address)
    gas_estimate = await provider.get_gas_estimate()
    base_fee = gas_estimate.base_fee_wei

    # ── Step 2.5: Balance check ──────────────────────────────────────────────
    if hasattr(provider, 'get_balance'):
        balance = await provider.get_balance(from_address)
        amount_wei = int(intent.amount_wei)
        # Rough gas cost estimate: gas_limit * (2 * base_fee + suggested_tip)
        est_gas_cost = 21_000 * (2 * base_fee + gas_estimate.max_priority_fee_wei)
        required = amount_wei + est_gas_cost
        if balance < required:
            raise PolicyError(
                f"Insufficient balance: wallet has {balance / 1e18:.6f} ETH "
                f"but tx needs ~{required / 1e18:.6f} ETH "
                f"(value {amount_wei / 1e18:.6f} + gas ~{est_gas_cost / 1e18:.6f})"
            )

    # ── Step 3: Compute fee fields with caps ─────────────────────────────────
    # Cap the tip: use node suggestion but never exceed policy.tip_wei
    tip = min(gas_estimate.max_priority_fee_wei, policy.tip_wei)

    # Standard EIP-1559 formula: max_fee = 2× base_fee + tip
    # Then hard-cap at: policy.max_fee_per_gas_multiplier × base_fee + tip
    standard_max_fee = 2 * base_fee + tip
    policy_cap = int(policy.max_fee_per_gas_multiplier * base_fee) + tip
    max_fee = min(standard_max_fee, policy_cap)

    value_wei = int(intent.amount_wei)

    # ── Step 3.5: Resolve calldata and gas limit ──────────────────────────────
    calldata_hex = getattr(intent, "calldata", "0x") or "0x"
    if calldata_hex and calldata_hex != "0x":
        calldata_bytes = bytes.fromhex(calldata_hex.lstrip("0x"))
        gas_limit = policy.gas_limit_contract_call
    else:
        calldata_bytes = b""
        gas_limit = policy.gas_limit_native_transfer

    # ── Step 4: Compute signing digest ───────────────────────────────────────
    digest = _compute_digest(
        chain_id=SEPOLIA_CHAIN_ID,
        nonce=nonce,
        max_priority_fee_per_gas=tip,
        max_fee_per_gas=max_fee,
        gas_limit=gas_limit,
        to=intent.to_address,
        value_wei=value_wei,
        data=calldata_bytes,
    )

    draft = DraftTx(
        intent_id=intent.intent_id,
        chain_id=SEPOLIA_CHAIN_ID,
        from_address=from_address.lower(),
        to=intent.to_address,
        value_wei=str(value_wei),
        data=calldata_hex,
        nonce=nonce,
        gas_limit=gas_limit,
        max_fee_per_gas=str(max_fee),
        max_priority_fee_per_gas=str(tip),
        digest=digest,
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=_APPROVAL_WINDOW_SECONDS),
    )

    # ── Step 5: Post-build validation (catches edge cases after field assembly)
    validate_draft_tx(draft, policy, base_fee)

    return draft

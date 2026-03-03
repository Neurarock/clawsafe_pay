"""
Data models for the transaction_builder module.

All monetary values are stored as decimal integer strings (e.g. "10000000000000000")
to avoid IEEE-754 floating-point imprecision and JSON integer overflow.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pydantic import BaseModel, Field, field_validator, model_validator

SEPOLIA_CHAIN_ID = 11155111
_EVM_ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")

# ── Extensible sets for multi-chain support ──────────────────────────────────
# Chain packages add to these sets when imported (see chains/ package).
SUPPORTED_CHAINS: set[str] = {"sepolia", "base"}
SUPPORTED_ASSETS: set[str] = {"ETH", "USDC", "USDT", "SOL", "BTC", "ZEC", "ADA"}

# Address regex per chain family (used by the validator below)
_ADDRESS_PATTERNS: dict[str, re.Pattern] = {
    "evm": re.compile(r"^0x[0-9a-fA-F]{40}$"),
    "solana": re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$"),
    "bitcoin": re.compile(r"^(1|3|bc1|m|n|2|tb1)[a-zA-HJ-NP-Z0-9]{25,62}$"),
    "zcash": re.compile(r"^(t1|t3|zs|u1|tm|t2|ztestsapling)[a-zA-Z0-9]{20,200}$"),
    "cardano": re.compile(r"^addr(1|_test1)[a-z0-9]{50,120}$"),
}

# Map chain slug → chain family (for address validation)
CHAIN_FAMILY: dict[str, str] = {
    "sepolia": "evm",
    "base": "evm",
}


class PaymentIntent(BaseModel):
    """Submitted by OpenClaw / publisher agent to initiate a transfer."""

    intent_id: str = Field(..., description="Unique UUID for this payment")
    from_user: str = Field(..., description="Payer user identifier")
    to_user: str = Field(..., description="Payee user identifier")
    chain: str = Field(default="sepolia", description="Target chain")
    asset: str = Field(default="ETH", description="Asset to transfer")
    amount_wei: str = Field(..., description="Transfer amount in smallest unit (decimal string)")
    to_address: str = Field(..., description="Recipient address")
    note: str = Field(default="", description="Human-readable memo")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    @field_validator("to_address")
    @classmethod
    def validate_address(cls, v: str) -> str:
        # EVM addresses are normalised to lowercase; others are left as-is.
        # Chain-specific validation happens in the model_validator below.
        if _EVM_ADDRESS_RE.match(v):
            return v.lower()
        return v

    @model_validator(mode="after")
    def validate_address_for_chain(self):
        """Validate to_address format matches the expected chain family."""
        family = CHAIN_FAMILY.get(self.chain)
        if family:
            pattern = _ADDRESS_PATTERNS.get(family)
            if pattern and not pattern.match(self.to_address):
                raise ValueError(
                    f"Invalid {family.upper()} address for chain {self.chain!r}: "
                    f"{self.to_address!r}"
                )
        # For chains without a registered family (placeholders), skip address validation
        return self

    @field_validator("amount_wei")
    @classmethod
    def validate_amount(cls, v: str) -> str:
        if not v.isdigit():
            raise ValueError("amount_wei must be a decimal integer string")
        if int(v) <= 0:
            raise ValueError("amount_wei must be positive")
        return v

    @field_validator("chain")
    @classmethod
    def validate_chain(cls, v: str) -> str:
        if v not in SUPPORTED_CHAINS:
            raise ValueError(
                f"Unsupported chain: {v!r}. Supported: {sorted(SUPPORTED_CHAINS)}"
            )
        return v

    @field_validator("asset")
    @classmethod
    def validate_asset(cls, v: str) -> str:
        if v not in SUPPORTED_ASSETS:
            raise ValueError(
                f"Unsupported asset: {v!r}. Supported: {sorted(SUPPORTED_ASSETS)}"
            )
        return v


class DraftTx(BaseModel):
    """
    Fully-specified unsigned EIP-1559 transaction ready for review and signing.
    All fee/value fields are decimal integer strings (wei).
    """

    intent_id: str
    tx_type: str = "eip1559"
    chain_id: int = SEPOLIA_CHAIN_ID
    from_address: str
    to: str
    value_wei: str
    data: str = "0x"
    nonce: int
    gas_limit: int
    max_fee_per_gas: str        # wei
    max_priority_fee_per_gas: str  # wei
    digest: str                 # keccak256 signing hash, 0x-prefixed 32-byte hex
    expires_at: datetime


class PolicyConfig(BaseModel):
    """
    Runtime policy constraints enforced before and after tx construction.
    Defaults are conservative MVP values (Sepolia testnet).
    """

    # Maximum transfer value
    max_amount_wei: int = Field(
        default=50_000_000_000_000_000,  # 0.05 ETH
        description="Hard cap on transfer value",
    )
    # Gas
    gas_limit_native_transfer: int = Field(
        default=21_000,
        description="Fixed gas limit for native ETH transfers",
    )
    # Fee cap: max_fee_per_gas <= multiplier * current_base_fee + tip
    max_fee_per_gas_multiplier: float = Field(
        default=2.0,
        description="Hard cap multiplier applied to current base fee",
    )
    # Tip cap (independently bounded to avoid tip-stuffing attacks)
    tip_wei: int = Field(
        default=1_500_000_000,  # 1.5 gwei
        description="Maximum maxPriorityFeePerGas in wei",
    )
    # Recipient allowlist — empty list = deny all, ["*"] = allow any
    recipient_allowlist: list[str] = Field(
        default_factory=list,
        description="Permitted destination addresses; use ['*'] to allow any address",
    )
    # Allowed chain IDs
    allowed_chain_ids: list[int] = Field(
        default_factory=lambda: [SEPOLIA_CHAIN_ID],
        description="Permitted chain IDs",
    )


class PolicyError(Exception):
    """Raised when a PaymentIntent or DraftTx violates policy."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class ProviderError(Exception):
    """Raised when an RPC/provider call fails."""

"""
Pydantic models for the signer_service.
"""

from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, Field


class SignRequest(BaseModel):
    """Incoming request to sign a transaction on any supported chain."""

    to: str = Field(..., description="Recipient address")
    value_wei: str = Field(..., description="Amount in smallest unit (decimal string)")
    data: str = Field(default="0x", description="Calldata hex (default: native transfer)")
    gas_limit: int = Field(default=21_000, description="Gas limit")
    user_id: str = Field(default="default_user", description="Identifier of the requesting user")
    note: str = Field(default="", description="Human-readable description of the transaction")
    chain: str = Field(default="sepolia", description="Target chain slug (e.g. sepolia, base)")
    from_address: str = Field(default="", description="Sender wallet address (empty = default wallet)")


class SignResponse(BaseModel):
    """Returned immediately when a sign request is submitted."""

    tx_id: str
    status: str
    message: str


class TxStatusResponse(BaseModel):
    """Full status of a signing request."""

    tx_id: str
    status: str  # pending_auth | approved | rejected | expired | broadcast | sign_failed
    to: str
    value_wei: str
    user_id: str
    note: str
    chain: str = "sepolia"
    auth_request_id: str | None = None
    signed_tx_hash: str | None = None
    raw_signed_tx: str | None = None
    error_reason: str | None = None
    created_at: str
    resolved_at: str | None = None


class AuthCallbackPayload(BaseModel):
    """Payload that user_auth POSTs back after the user responds."""

    request_id: str
    status: str  # approved | rejected | expired

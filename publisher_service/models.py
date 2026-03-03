"""
Pydantic request/response models for publisher_service.
"""
from __future__ import annotations

from typing import Optional
from pydantic import BaseModel

# Re-use models from transaction_builder directly
from transaction_builder.models import PaymentIntent, DraftTx  # noqa: F401 (re-exported)


class IntentResponse(BaseModel):
    intent_id: str
    status: str
    message: str


class IntentStatusResponse(BaseModel):
    intent_id: str
    status: str
    from_user: str
    to_user: str
    to_address: str
    amount_wei: str
    note: str
    created_at: str
    updated_at: str
    draft_tx: Optional[dict] = None
    review_report: Optional[dict] = None
    tx_hash: Optional[str] = None
    error_message: Optional[str] = None


class ReviewReport(BaseModel):
    intent_id: str
    digest: str
    verdict: str          # "OK" | "WARN" | "BLOCK"
    reasons: list[str]
    summary: str
    gas_assessment: dict
    model_used: str = ""


class SignerSubmitResponse(BaseModel):
    """Response from signer_service POST /sign (202 Accepted)."""
    tx_id: str
    status: str
    message: str


class SignerStatusResponse(BaseModel):
    """Response from signer_service GET /sign/{tx_id}."""
    tx_id: str
    status: str  # pending_auth | approved | rejected | expired | signed | sign_failed
    to: str
    value_wei: str
    user_id: str
    note: str
    auth_request_id: Optional[str] = None
    signed_tx_hash: Optional[str] = None
    raw_signed_tx: Optional[str] = None
    error_reason: Optional[str] = None
    created_at: str
    resolved_at: Optional[str] = None

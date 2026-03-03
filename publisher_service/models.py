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


class SignerResponse(BaseModel):
    tx_hash: str
    signed_at: str

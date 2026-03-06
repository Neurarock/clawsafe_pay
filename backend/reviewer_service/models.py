"""
Pydantic models for reviewer_service.
"""
from __future__ import annotations

from typing import Optional
from pydantic import BaseModel


class ReviewRequest(BaseModel):
    intent_id: str
    draft_tx: dict
    current_base_fee_wei: int
    calldata_description: str = ""


class GasAssessment(BaseModel):
    estimated_total_fee_wei: str
    is_reasonable: bool
    reference: str


class ReviewReport(BaseModel):
    intent_id: str
    digest: str
    verdict: str              # "OK" | "WARN" | "BLOCK"
    reasons: list[str]
    summary: str
    gas_assessment: dict
    model_used: str = ""

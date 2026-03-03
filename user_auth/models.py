"""
Pydantic models shared across the user_auth service.
"""

from pydantic import BaseModel, Field


class AuthRequest(BaseModel):
    """Incoming auth request from signer_service."""

    request_id: str = Field(..., description="Unique UUID for this transaction")
    user_id: str = Field(..., description="Identifier of the user to authenticate")
    action: str = Field(..., description="Human-readable description of the requested action")
    hmac_digest: str = Field(
        ...,
        description="HMAC-SHA256 digest computed over request_id:user_id:action with the shared secret",
    )


class AuthResponse(BaseModel):
    """Returned to signer_service when a request is created."""

    request_id: str
    status: str
    message: str


class AuthStatusResponse(BaseModel):
    """Response for the GET /auth/{request_id} status endpoint."""

    request_id: str
    user_id: str
    action: str
    status: str
    created_at: str
    resolved_at: str | None = None


class TelegramUpdate(BaseModel):
    """
    Minimal Telegram webhook update model (only the fields we care about).
    """

    update_id: int
    callback_query: dict | None = None


class SignerCallbackPayload(BaseModel):
    """Payload received by the mock signer_service callback endpoint."""

    request_id: str
    status: str

"""
Pydantic request/response models for the API user management system.
"""
from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field


class CreateApiUser(BaseModel):
    """Request body for creating a new API user (agent)."""
    name: str = Field(..., min_length=1, max_length=100, description="Display name for the agent")
    telegram_chat_id: str = Field(
        default="",
        description="Telegram chat ID for auth notifications. If empty, uses the global default.",
    )
    allowed_assets: list[str] = Field(
        default=["*"],
        description='Token symbols this agent can transact (e.g. ["ETH","USDC"]). ["*"] = all.',
    )
    allowed_chains: list[str] = Field(
        default=["*"],
        description='Chain slugs this agent can use (e.g. ["sepolia","base"]). ["*"] = all.',
    )
    max_amount_wei: str = Field(
        default="0",
        description="Max amount per single transaction in wei. 0 = unlimited.",
    )
    daily_limit_wei: str = Field(
        default="0",
        description="Max total daily spend in wei. 0 = unlimited.",
    )
    rate_limit: int = Field(
        default=0,
        ge=0,
        description="Max requests per minute for this agent. 0 = use server default.",
    )


class UpdateApiUser(BaseModel):
    """Request body for updating an API user. All fields optional."""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    telegram_chat_id: Optional[str] = None
    allowed_assets: Optional[list[str]] = None
    allowed_chains: Optional[list[str]] = None
    max_amount_wei: Optional[str] = None
    daily_limit_wei: Optional[str] = None
    rate_limit: Optional[int] = Field(None, ge=0)
    is_active: Optional[bool] = None


class ApiUserResponse(BaseModel):
    """Returned for all API user operations (except create, which adds api_key)."""
    id: str
    name: str
    api_key_prefix: str
    telegram_chat_id_set: bool = Field(
        default=False,
        description="Whether a Telegram chat ID has been configured (the actual ID is hidden).",
    )
    allowed_assets: list[str]
    allowed_chains: list[str]
    max_amount_wei: str
    daily_limit_wei: str
    rate_limit: int
    is_active: bool
    created_at: str
    updated_at: str


class ApiUserCreatedResponse(ApiUserResponse):
    """Returned only on creation — includes the plaintext API key."""
    api_key: str = Field(
        ...,
        description="The full API key. Shown only once — store it securely.",
    )


class ApiKeyRegeneratedResponse(ApiUserResponse):
    """Returned when an API key is regenerated."""
    api_key: str = Field(
        ...,
        description="The new API key. The old key is permanently invalidated.",
    )


class ApiUserUsageResponse(BaseModel):
    id: str
    name: str
    today_total_wei: str
    today_request_count: int
    daily_limit_wei: str
    limit_remaining_wei: str

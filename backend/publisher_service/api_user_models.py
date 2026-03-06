"""
Pydantic request/response models for the API user management system.
"""
from __future__ import annotations

from typing import Literal
from typing import Optional
from pydantic import BaseModel, Field

BotType = Literal[
    "personal", "ecommerce", "dca_trader", "spot_trader",
    "nft_sniper", "pump_fun_sniper", "polymarket_copytrader",
    "defi_borrower", "custom",
]
ApprovalMode = Literal["always_human", "auto_within_limits", "human_if_above_threshold"]

# ── Policy Chat ───────────────────────────────────────────────────────────────

class PolicyChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class PolicyChatRequest(BaseModel):
    messages: list[PolicyChatMessage] = Field(default=[])
    user_message: str = Field(..., min_length=1, max_length=2000)


class PolicyChatResponse(BaseModel):
    type: Literal["message", "draft"]
    content: Optional[str] = None
    draft: Optional[dict] = None
    messages: list[dict]


# ── Policy Generation ─────────────────────────────────────────────────────────

class GeneratePolicyRequest(BaseModel):
    """Request body for Z.AI-powered policy generation."""
    bot_goal: str = Field(..., min_length=10, max_length=500)
    bot_type: BotType = Field(default="custom")
    allowed_assets: list[str] = Field(default=["*"])
    allowed_chains: list[str] = Field(default=["*"])


class GeneratePolicyResponse(BaseModel):
    """Policy suggestion returned by Z.AI GLM."""
    approval_mode: ApprovalMode
    approval_threshold_wei: str
    window_limit_wei: str
    window_seconds: int
    max_amount_wei: str
    daily_limit_wei: str
    allowed_contracts: list[str]
    allowed_assets: list[str]
    allowed_chains: list[str]
    reasoning: list[str]
    policy_summary: str
    model_used: str


class CreateApiUser(BaseModel):
    """Request body for creating a new API user (agent)."""
    name: str = Field(..., min_length=1, max_length=100, description="Display name for the agent")
    telegram_chat_id: str = Field(
        default="",
        description="Telegram chat ID for auth notifications. If empty, uses the global default.",
    )
    bot_type: BotType = Field(
        default="personal",
        description="High-level bot category used to drive default policy posture.",
    )
    bot_goal: str = Field(
        ...,
        min_length=3,
        max_length=500,
        description="High-level project description or goal for the bot.",
    )
    allowed_assets: list[str] = Field(
        default=["*"],
        description='Token symbols this agent can transact (e.g. ["ETH","USDC"]). ["*"] = all.',
    )
    allowed_chains: list[str] = Field(
        default=["*"],
        description='Chain slugs this agent can use (e.g. ["sepolia","base"]). ["*"] = all.',
    )
    allowed_contracts: list[str] = Field(
        default=["*"],
        description='Contract/recipient addresses this agent can interact with. ["*"] = unrestricted.',
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
    approval_mode: ApprovalMode = Field(
        default="always_human",
        description="Approval matrix mode for this bot.",
    )
    approval_threshold_wei: str = Field(
        default="0",
        description="Used by human_if_above_threshold mode. 0 = always require human.",
    )
    window_limit_wei: str = Field(
        default="0",
        description="Rolling spend-window cap in wei. 0 = unlimited.",
    )
    window_seconds: int = Field(
        default=0,
        ge=0,
        description="Rolling window size in seconds for window_limit_wei. 0 = disabled.",
    )


class UpdateApiUser(BaseModel):
    """Request body for updating an API user. All fields optional."""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    telegram_chat_id: Optional[str] = None
    bot_type: Optional[BotType] = None
    bot_goal: Optional[str] = Field(None, min_length=3, max_length=500)
    allowed_assets: Optional[list[str]] = None
    allowed_chains: Optional[list[str]] = None
    allowed_contracts: Optional[list[str]] = None
    max_amount_wei: Optional[str] = None
    daily_limit_wei: Optional[str] = None
    rate_limit: Optional[int] = Field(None, ge=0)
    approval_mode: Optional[ApprovalMode] = None
    approval_threshold_wei: Optional[str] = None
    window_limit_wei: Optional[str] = None
    window_seconds: Optional[int] = Field(None, ge=0)
    is_active: Optional[bool] = None


class ApiUserResponse(BaseModel):
    """Returned for all API user operations (except create, which adds api_key)."""
    id: str
    name: str
    bot_type: BotType
    bot_goal: str
    api_key_prefix: str
    telegram_chat_id_set: bool = Field(
        default=False,
        description="Whether a Telegram chat ID has been configured (the actual ID is hidden).",
    )
    allowed_assets: list[str]
    allowed_chains: list[str]
    allowed_contracts: list[str]
    max_amount_wei: str
    daily_limit_wei: str
    rate_limit: int
    approval_mode: ApprovalMode
    approval_threshold_wei: str
    window_limit_wei: str
    window_seconds: int
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


# ── Agent Instruction Chat ─────────────────────────────────────────────────────

class InstructionChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class AgentInstructionRequest(BaseModel):
    instruction: str = Field(..., min_length=1, max_length=1000)
    from_address: str = Field(default="", description="Wallet address the agent is acting from")
    messages: list[InstructionChatMessage] = Field(default=[])


class TransactionPlan(BaseModel):
    """Structured transaction plan returned by Z.AI when it has enough info."""
    to_address: str
    value_wei: str
    asset: str
    note: str
    reasoning: list[str]
    needs_human: bool


class AgentInstructionResponse(BaseModel):
    type: Literal["message", "plan"]
    content: Optional[str] = None
    plan: Optional[TransactionPlan] = None
    messages: list[dict]
    model_used: str

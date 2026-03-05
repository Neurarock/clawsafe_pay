"""
Pydantic request/response models for wallet management.
"""
from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field


class AddWallet(BaseModel):
    """Request body for adding a new wallet."""
    address: str = Field(
        ...,
        min_length=10,
        max_length=128,
        description="The wallet address (e.g. 0x...)",
    )
    private_key: str = Field(
        ...,
        min_length=10,
        max_length=256,
        description="The wallet private key (hex). Encrypted at rest.",
    )
    label: str = Field(
        default="",
        max_length=100,
        description="Optional friendly label for this wallet.",
    )
    chain: str = Field(
        default="sepolia",
        description="Chain this wallet is used on (e.g. sepolia, base).",
    )


class WalletResponse(BaseModel):
    """Returned for wallet list/get operations. Never exposes the private key."""
    id: str
    address: str
    label: str
    chain: str
    is_default: bool
    created_at: str


class WalletBalanceResponse(BaseModel):
    """Balance information for a wallet."""
    address: str
    chain: str
    balance_wei: str
    balance_display: str
    symbol: str

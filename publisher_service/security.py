"""
Security helpers for publisher_service.

Supports two authentication modes:
  1. **Admin key** (PUBLISHER_API_KEY env var) – full access, used by the
     dashboard and for managing API users.
  2. **Agent key** (per-user keys stored in the DB) – access governed by
     the agent's permissions (allowed assets, chains, limits).
"""
from __future__ import annotations

import hmac
import logging
from typing import Optional

import publisher_service.config as config
from fastapi import Header, HTTPException, Request

logger = logging.getLogger("publisher_service.security")


def _is_admin_key(provided: str) -> bool:
    """Constant-time comparison against the admin PUBLISHER_API_KEY."""
    expected = config.PUBLISHER_API_KEY.encode()
    return hmac.compare_digest(provided.encode(), expected)


def verify_api_key(provided: str) -> bool:
    """Check if *provided* matches the admin key OR an active agent key."""
    if _is_admin_key(provided):
        return True
    # Lazy import to avoid circular deps at module load
    from publisher_service.api_users_db import get_api_user_by_key
    user = get_api_user_by_key(provided)
    return user is not None


async def require_api_key(request: Request, x_api_key: str = Header(...)):
    """Dependency that validates the API key and attaches agent context.

    After this dependency runs the request state contains:
      - request.state.is_admin  (bool)
      - request.state.api_user  (dict | None) — the agent record if not admin
    """
    if _is_admin_key(x_api_key):
        request.state.is_admin = True
        request.state.api_user = None
        return

    from publisher_service.api_users_db import get_api_user_by_key
    user = get_api_user_by_key(x_api_key)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid API key")

    request.state.is_admin = False
    request.state.api_user = user


async def require_admin_key(x_api_key: str = Header(...)):
    """Dependency that requires the admin key specifically."""
    if not _is_admin_key(x_api_key):
        raise HTTPException(status_code=403, detail="Admin API key required")


def check_agent_permission(
    api_user: Optional[dict],
    *,
    chain: str = "",
    asset: str = "",
    amount_wei: str = "0",
) -> None:
    """Raise HTTPException if the agent lacks permission for the operation.

    Admins (api_user=None) are always allowed.
    """
    if api_user is None:
        return  # admin — no restrictions

    # ── Asset check ──────────────────────────────────────────────────
    allowed_assets = api_user.get("allowed_assets", ["*"])
    if "*" not in allowed_assets and asset.upper() not in [a.upper() for a in allowed_assets]:
        raise HTTPException(
            status_code=403,
            detail=f"Agent '{api_user['name']}' is not permitted to transact {asset}. "
                   f"Allowed: {allowed_assets}",
        )

    # ── Chain check ──────────────────────────────────────────────────
    allowed_chains = api_user.get("allowed_chains", ["*"])
    if "*" not in allowed_chains and chain.lower() not in [c.lower() for c in allowed_chains]:
        raise HTTPException(
            status_code=403,
            detail=f"Agent '{api_user['name']}' is not permitted on chain {chain}. "
                   f"Allowed: {allowed_chains}",
        )

    # ── Per-tx amount check ──────────────────────────────────────────
    max_wei = api_user.get("max_amount_wei", "0")
    if max_wei and max_wei != "0" and int(amount_wei) > int(max_wei):
        raise HTTPException(
            status_code=403,
            detail=f"Amount {amount_wei} exceeds per-transaction limit of {max_wei} wei "
                   f"for agent '{api_user['name']}'.",
        )

    # ── Daily limit check ────────────────────────────────────────────
    daily_limit = api_user.get("daily_limit_wei", "0")
    if daily_limit and daily_limit != "0":
        from publisher_service.api_users_db import get_daily_usage
        usage = get_daily_usage(api_user["id"])
        projected = int(usage["total_wei"]) + int(amount_wei)
        if projected > int(daily_limit):
            remaining = int(daily_limit) - int(usage["total_wei"])
            raise HTTPException(
                status_code=403,
                detail=f"Daily limit exceeded for agent '{api_user['name']}'. "
                       f"Limit: {daily_limit} wei, used today: {usage['total_wei']} wei, "
                       f"remaining: {max(0, remaining)} wei.",
            )

"""
Security helpers: HMAC signing, verification, and anti-replay checks.
"""

import hashlib
import hmac

from user_auth.config import HMAC_SECRET


def compute_hmac(request_id: str, user_id: str, action: str) -> str:
    """
    Compute HMAC-SHA256 over the canonical fields of an auth request.
    The signer_service must use the same shared secret and field ordering.
    """
    message = f"{request_id}:{user_id}:{action}"
    return hmac.new(
        HMAC_SECRET.encode(),
        message.encode(),
        hashlib.sha256,
    ).hexdigest()


def verify_hmac(request_id: str, user_id: str, action: str, digest: str) -> bool:
    """Constant-time comparison of a supplied digest against the expected one."""
    expected = compute_hmac(request_id, user_id, action)
    return hmac.compare_digest(expected, digest)

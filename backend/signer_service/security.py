"""
HMAC helper — mirrors user_auth/security.py so both services produce the same digest.
"""

import hashlib
import hmac

from signer_service.config import HMAC_SECRET


def compute_hmac(request_id: str, user_id: str, action: str) -> str:
    message = f"{request_id}:{user_id}:{action}"
    return hmac.new(HMAC_SECRET.encode(), message.encode(), hashlib.sha256).hexdigest()

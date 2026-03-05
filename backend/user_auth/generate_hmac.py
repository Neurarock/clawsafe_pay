"""
Helper script to generate a valid HMAC digest for testing.

Usage:
    python -m user_auth.generate_hmac <request_id> <user_id> <action>

Example:
    python -m user_auth.generate_hmac "abc-123" "user42" "Sign contract #7"
"""

import sys
from user_auth.security import compute_hmac


def main():
    if len(sys.argv) != 4:
        print("Usage: python -m user_auth.generate_hmac <request_id> <user_id> <action>")
        sys.exit(1)

    request_id, user_id, action = sys.argv[1], sys.argv[2], sys.argv[3]
    digest = compute_hmac(request_id, user_id, action)
    print(f"HMAC digest: {digest}")
    print()
    print("curl payload:")
    print(
        f'  {{"request_id": "{request_id}", "user_id": "{user_id}", '
        f'"action": "{action}", "hmac_digest": "{digest}"}}'
    )


if __name__ == "__main__":
    main()

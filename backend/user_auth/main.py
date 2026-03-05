"""
Entry-point for the user_auth service.

    python -m user_auth.main
    # or
    uvicorn user_auth.app:app --host 0.0.0.0 --port 8000 --reload
"""

import uvicorn

from user_auth.config import AUTH_SERVICE_HOST, AUTH_SERVICE_PORT

if __name__ == "__main__":
    uvicorn.run(
        "user_auth.app:app",
        host=AUTH_SERVICE_HOST,
        port=AUTH_SERVICE_PORT,
        reload=True,
    )

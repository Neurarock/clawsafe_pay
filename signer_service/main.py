"""
Entry-point for the signer_service.

    python -m signer_service.main
"""

import uvicorn
from signer_service.config import SIGNER_SERVICE_HOST, SIGNER_SERVICE_PORT

if __name__ == "__main__":
    uvicorn.run(
        "signer_service.app:app",
        host=SIGNER_SERVICE_HOST,
        port=SIGNER_SERVICE_PORT,
        reload=True,
    )

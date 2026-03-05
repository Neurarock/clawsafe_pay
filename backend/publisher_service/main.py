"""
Entry-point for the publisher_service.

    python -m publisher_service.main
"""

import uvicorn
from publisher_service.config import PUBLISHER_SERVICE_PORT

if __name__ == "__main__":
    uvicorn.run(
        "publisher_service.app:app",
        host="0.0.0.0",
        port=PUBLISHER_SERVICE_PORT,
        reload=True,
    )

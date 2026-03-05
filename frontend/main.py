"""
Entry-point for the dashboard frontend service.

    python -m frontend.main
"""

import uvicorn
from frontend.config import DASHBOARD_PORT

if __name__ == "__main__":
    uvicorn.run(
        "frontend.app:app",
        host="0.0.0.0",
        port=DASHBOARD_PORT,
        reload=True,
    )

"""
Entry-point for the dashboard frontend service.

    python -m dashboard.main
"""

import uvicorn
from dashboard.config import DASHBOARD_PORT

if __name__ == "__main__":
    uvicorn.run(
        "dashboard.app:app",
        host="0.0.0.0",
        port=DASHBOARD_PORT,
        reload=True,
    )

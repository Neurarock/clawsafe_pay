"""
Entry point for reviewer_service.

Run with:
    python -m reviewer_service.main
"""
import uvicorn
import reviewer_service.config as config

if __name__ == "__main__":
    uvicorn.run(
        "reviewer_service.app:app",
        host="0.0.0.0",
        port=config.REVIEWER_SERVICE_PORT,
        reload=False,
    )

"""
Mock signer_service server.

Run this alongside the user_auth service to test the full callback flow.
It exposes a single endpoint that receives auth results from user_auth.

    uvicorn signer_service.mock_server:app --port 8001
"""

import logging

from fastapi import FastAPI
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s  %(message)s")
logger = logging.getLogger("signer_service.mock")

app = FastAPI(title="Signer Service (mock)", version="0.1.0")


class AuthCallback(BaseModel):
    request_id: str
    status: str  # approved | rejected | expired


@app.post("/auth/callback")
async def receive_auth_callback(payload: AuthCallback):
    """
    Mock endpoint that simply logs the callback from user_auth.
    In production this would resume the signing workflow.
    """
    logger.info(
        "🔔 Received auth callback — request_id=%s  status=%s",
        payload.request_id,
        payload.status,
    )
    return {"received": True, "request_id": payload.request_id, "status": payload.status}


@app.get("/health")
async def health():
    return {"status": "ok"}

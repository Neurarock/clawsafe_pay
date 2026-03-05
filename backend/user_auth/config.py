"""
Configuration and settings for the user_auth service.
Loads from environment variables with sensible defaults.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from project root
load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

# --- Telegram Bot Settings ---
TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")

# --- Signer Service Callback ---
SIGNER_SERVICE_CALLBACK_URL: str = os.getenv(
    "SIGNER_SERVICE_CALLBACK_URL",
    "http://localhost:8001/auth/callback",
)

# --- Service Settings ---
AUTH_SERVICE_HOST: str = os.getenv("AUTH_SERVICE_HOST", "0.0.0.0")
AUTH_SERVICE_PORT: int = int(os.getenv("AUTH_SERVICE_PORT", "8000"))

# --- Security Settings ---
# HMAC shared secret for request signing between services
HMAC_SECRET: str = os.getenv("HMAC_SECRET", "change-me-in-production")

# How many seconds an auth request stays valid before auto-expiring
AUTH_REQUEST_TTL_SECONDS: int = int(os.getenv("AUTH_REQUEST_TTL_SECONDS", "300"))  # 5 min

# --- Database ---
DATABASE_PATH: str = os.getenv(
    "DATABASE_PATH",
    str(Path(__file__).resolve().parent / "auth_requests.db"),
)

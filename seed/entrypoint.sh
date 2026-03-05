#!/bin/sh
# ── Docker entrypoint wrapper ─────────────────────────────────────────
# Applies seed data (if configured) before starting the service.
# Set SEED_DB_PATH and SEED_SQL_PATH environment variables to enable.
set -e

# Apply seed data when both env vars are present
if [ -n "$SEED_DB_PATH" ] && [ -n "$SEED_SQL_PATH" ]; then
    python /app/seed/apply.py
fi

# Hand off to the original CMD
exec "$@"

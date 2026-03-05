# ── user_auth ─────────────────────────────────────────────────────────
FROM python:3.11-slim

WORKDIR /app

# Install user_auth requirements
COPY backend/user_auth/requirements.txt /tmp/user_auth.txt
RUN pip install --no-cache-dir -r /tmp/user_auth.txt

# Copy backend packages
COPY backend/ /app/backend/

# Backend packages are importable via PYTHONPATH
ENV PYTHONPATH=/app/backend

EXPOSE 8000

CMD ["python", "-m", "user_auth.main"]

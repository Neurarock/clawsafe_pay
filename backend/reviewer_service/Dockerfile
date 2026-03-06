# ── reviewer_service ──────────────────────────────────────────────────
FROM python:3.11-slim

WORKDIR /app

# Install requirements
COPY backend/reviewer_service/requirements.txt /tmp/reviewer.txt
RUN pip install --no-cache-dir -r /tmp/reviewer.txt

# Copy backend packages
COPY backend/ /app/backend/

# Backend packages are importable via PYTHONPATH
ENV PYTHONPATH=/app/backend

EXPOSE 8003

CMD ["python", "-m", "reviewer_service.main"]

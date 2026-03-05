# ── frontend (dashboard) ──────────────────────────────────────────────
FROM python:3.11-slim

WORKDIR /app

# Install frontend requirements
COPY frontend/requirements.txt /tmp/frontend.txt
RUN pip install --no-cache-dir -r /tmp/frontend.txt

# Copy the frontend package
COPY frontend/ /app/frontend/

# Frontend package is importable from /app
ENV PYTHONPATH=/app

EXPOSE 8008

CMD ["python", "-m", "frontend.main"]

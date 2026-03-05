# ── publisher_service ─────────────────────────────────────────────────
FROM python:3.11-slim

WORKDIR /app

# Install backend requirements (publisher + shared libs)
COPY backend/publisher_service/requirements.txt /tmp/publisher.txt
COPY backend/transaction_builder/requirements.txt /tmp/txbuilder.txt
RUN pip install --no-cache-dir -r /tmp/publisher.txt -r /tmp/txbuilder.txt

# Copy backend packages
COPY backend/ /app/backend/

# Backend packages are importable via PYTHONPATH
ENV PYTHONPATH=/app/backend

EXPOSE 8002

CMD ["python", "-m", "publisher_service.main"]

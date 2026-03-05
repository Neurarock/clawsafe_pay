# ── signer_service ────────────────────────────────────────────────────
FROM python:3.11-slim

WORKDIR /app

# Install signer requirements (includes web3 which chains also needs)
COPY backend/signer_service/requirements.txt /tmp/signer.txt
RUN pip install --no-cache-dir -r /tmp/signer.txt

# Copy backend packages
COPY backend/ /app/backend/

# Copy seed data + entrypoint
COPY seed/ /app/seed/
RUN chmod +x /app/seed/entrypoint.sh

# Backend packages are importable via PYTHONPATH
ENV PYTHONPATH=/app/backend

EXPOSE 8001

ENTRYPOINT ["/app/seed/entrypoint.sh"]
CMD ["python", "-m", "signer_service.main"]

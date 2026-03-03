# Publisher Service

`publisher_service` is the payment orchestrator for ClawSafe Pay.

It accepts a `PaymentIntent`, builds a draft Sepolia transaction, gets reviewer input, then submits to signer_service which handles Telegram approval, signing, and broadcasting to the network.

## What It Does

- Receives payment intents from upstream agent/OpenClaw.
- Runs the end-to-end workflow:
  - build tx draft
  - reviewer check
  - submit to signer_service (handles auth + signing + broadcasting)
  - poll signer for result
  - store tx hash and final status
- Persists workflow state in SQLite for polling/audit.

## Main Endpoints

- `POST /intent`  
  Accepts a `PaymentIntent`, stores it, and starts async processing.
- `GET /intent/{intent_id}`  
  Returns current status + stored draft/review/tx hash/error.
- `GET /health`  
  Health check.

All intent endpoints require `X-API-Key`.

## State Machine

Normal path:

`pending -> building -> reviewing -> signing -> broadcast -> confirmed`

Terminal error/decision states:

`rejected`, `expired`, `blocked`, `failed`

## How It Works Internally

1. Load intent from DB and construct transaction-builder `PaymentIntent`.
2. Build `DraftTx` via `transaction_builder`.
3. Call `reviewer_service` for verdict (`OK|WARN|BLOCK`).
4. Enforce digest consistency (`review.digest` must match `draft.digest`).
5. Submit to `signer_service` (`POST /sign`).
6. Poll `signer_service` (`GET /sign/{tx_id}`) for result.
7. Signer handles Telegram auth, signs the tx, and broadcasts to the network.
8. Store `tx_hash` and mark status `confirmed`.

## Safety Checks

- Policy enforcement happens during draft build (amount caps, allowlist, gas/fee constraints).
- Reviewer `BLOCK` stops the flow.
- Digest mismatch between draft and review is treated as a security failure.
- Approval timeout and explicit reject are terminal states.
- DB prevents transitions out of terminal states.

## Key Files

- `app.py` - FastAPI routes + middleware
- `orchestrator.py` - workflow/state transitions
- `clients.py` - downstream HTTP calls
- `database.py` - SQLite persistence
- `security.py` - API key + HMAC helpers
- `config.py` - env-based configuration

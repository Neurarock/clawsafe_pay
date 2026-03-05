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

### Wallet Management (admin-only)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/wallets` | List all wallet addresses (DB + env-configured). No auth required. |
| `POST` | `/wallets` | Add a wallet (address + private key). Encrypted at rest. Admin key required. |
| `GET` | `/wallets/managed` | List all DB-managed wallets (no private keys exposed). Admin key required. |
| `DELETE` | `/wallets/{wallet_id}` | Delete a wallet by ID. Admin key required. |
| `POST` | `/wallets/{wallet_id}/set-default` | Set a wallet as the default sending wallet. Admin key required. |
| `GET` | `/wallets/balances` | Fetch on-chain ETH balances for all wallets via RPC. No auth required. |

**Private key security:**
- Private keys are encrypted with XOR + SHA-256 derived key before storage in SQLite.
- The encryption secret is configured via the `WALLET_ENC_SECRET` environment variable.
- Private keys are **never** returned by any API endpoint.
- For production, use a proper KMS (AWS KMS, HashiCorp Vault, etc.) instead of the built-in encryption.

**Wallet sources:**
- **DB wallets** — added via `POST /wallets`, stored in the `wallets` SQLite table.
- **Env wallets** — loaded from `WALLET_ADDR_N` environment variables at startup (read-only).
- The `GET /wallets` endpoint merges both sources, with DB wallets taking priority.

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
- `database.py` - SQLite persistence (payment intents)
- `wallets_db.py` - SQLite persistence (wallet management)
- `wallet_models.py` - Pydantic models for wallet endpoints
- `api_users_db.py` - SQLite persistence (API user/agent management)
- `api_user_models.py` - Pydantic models for API user endpoints
- `security.py` - API key + HMAC helpers
- `config.py` - env-based configuration

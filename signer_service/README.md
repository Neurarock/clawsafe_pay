# Signer Service

Sepolia testnet transaction signing service for **ClawSafe Pay**.

Accepts transaction requests, obtains Telegram-based 2FA approval via the `user_auth` service, then signs and broadcasts the transaction to the Sepolia network. The on-chain transaction hash and raw signed transaction are stored and returned.

---

## Architecture

```
caller                    signer_service                user_auth               Telegram
  │                            │                            │                      │
  │  POST /sign                │                            │                      │
  │ ────────────────────────►  │                            │                      │
  │  ◄── 200 {tx_id, pending}  │                            │                      │
  │                            │  POST /auth/request        │                      │
  │                            │ ────────────────────────►  │  sendMessage         │
  │                            │                            │ ──────────────────►   │
  │                            │                            │                      │
  │                            │  GET /auth/{id} (poll)     │  callback_query      │
  │                            │ ────────────────────────►  │ ◄──────────────────   │
  │                            │  ◄── {status: approved}    │                      │
  │                            │                            │                      │
  │                            │  [sign tx with web3]       │                      │
  │                            │  [broadcast to network]    │                      │
  │                            │                            │                      │
  │  GET /sign/{tx_id}         │                            │                      │
  │ ────────────────────────►  │                            │                      │
  │  ◄── {status: broadcast, …}  │                            │                      │
```

---

## Transaction Lifecycle

| Status | Meaning |
|--------|---------|
| `pending_auth` | Waiting for Telegram approval |
| `approved` | User approved; signing & broadcasting in progress |
| `rejected` | User rejected the transaction |
| `expired` | Auth request timed out (5 min default) |
| `broadcast` | Transaction signed and broadcast to the network; on-chain tx hash available |
| `sign_failed` | Signing or broadcasting failed (RPC error, insufficient funds, etc.) |

---

## Prerequisites

| Requirement | Version |
|-------------|---------|
| Python | 3.11+ |
| `user_auth` service | Running on port 8000 |
| Sepolia RPC | Any public or Infura/Alchemy endpoint |

---

## Quick Start

### 1. Install dependencies

```bash
pip install -r signer_service/requirements.txt
```

### 2. Configure `.env`

Add these to the project root `.env` (some may already exist):

```dotenv
# Wallet (Sepolia testnet)
WALLET_ADDR_2=0x52492C6B4635E6b87f2043A6Ac274Be458060b48
WALLET_PRIV_KEY_2=0x...your_private_key...

# Sepolia RPC (optional — defaults to https://rpc.sepolia.org)
# SEPOLIA_RPC_URL=https://sepolia.infura.io/v3/<YOUR_KEY>

# user_auth service URL
USER_AUTH_URL=http://localhost:8000

# HMAC secret (must match user_auth)
HMAC_SECRET=ckDhTstYUaZok/gdcVLp7+jLAY/q3E9dPKQUZWIAmAI=

# Signer service port
SIGNER_SERVICE_PORT=8001
```

### 3. Initialise the database

```bash
python -m signer_service.database
```

### 4. Start both services

```bash
# Terminal 1 — user_auth (port 8000)
uvicorn user_auth.app:app --reload --port 8000

# Terminal 2 — signer_service (port 8001)
uvicorn signer_service.app:app --reload --port 8001
```

### 5. Submit a transaction

```bash
curl -X POST http://localhost:8001/sign \
  -H "Content-Type: application/json" \
  -d '{
    "to": "0x1234567890abcdef1234567890abcdef12345678",
    "value_wei": "10000000000000000",
    "user_id": "user42",
    "note": "Pay Alice 0.01 ETH"
  }'
```

Response:
```json
{
  "tx_id": "a1b2c3d4-...",
  "status": "pending_auth",
  "message": "Transaction queued — waiting for Telegram approval"
}
```

### 6. Approve in Telegram

You'll receive a message like:

```
🔐  AUTHORIZATION REQUIRED
━━━━━━━━━━━━━━━━━━━━━━

📋  Action:  Sign transaction: send 0.010000 ETH to 0x1234...5678 — Pay Alice 0.01 ETH

👤  Requested by:  user42
🆔  Ref:  a1b2c3d4…

━━━━━━━━━━━━━━━━━━━━━━
⏳  This request will expire in 5 minutes.
⚠️  Only approve if you initiated this transaction.
```

Tap **Approve** or **Reject**.

### 7. Check status

```bash
curl http://localhost:8001/sign/<tx_id>
```

If approved and broadcast:
```json
{
  "tx_id": "a1b2c3d4-...",
  "status": "broadcast",
  "to": "0x1234567890abcdef1234567890abcdef12345678",
  "value_wei": "10000000000000000",
  "signed_tx_hash": "0xabc...",
  "raw_signed_tx": "0x02f8..."
}
```

---

## API Reference

### `POST /sign`

Submit a transaction for signing.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `to` | string | Yes | Recipient address (0x-prefixed) |
| `value_wei` | string | Yes | Amount in wei (decimal string) |
| `data` | string | No | Calldata hex (default: `0x`) |
| `gas_limit` | int | No | Gas limit (default: 21000) |
| `user_id` | string | No | User identifier (default: `default_user`) |
| `note` | string | No | Human-readable memo |

### `GET /sign/{tx_id}`

Returns the full status of a signing request.

### `POST /auth/callback`

Receives auth results from `user_auth` (secondary notification).

### `GET /health`

Returns `{"status": "ok", "wallet": "<configured_address>"}`.

---

## Security

| Feature | Description |
|---------|-------------|
| **Unique UUID per transaction** | Each signing request generates a fresh UUID for `user_auth`. Old auth results cannot be reused for new transactions. |
| **HMAC-SHA256 signing** | Auth requests are HMAC-signed with a shared secret. |
| **Telegram 2FA** | Every transaction requires explicit human approval via Telegram inline buttons. |
| **Auto-expiry** | Unapproved requests expire after 5 minutes. |
| **No private key exposure** | The private key is only loaded from env vars and used in-memory for signing. Never logged or returned via API. |
| **Rate limiting** | Per-IP rate limiter (20 req/min). |

### Wallet Key Sources

The signer service loads private keys from two sources:

1. **Environment variables** (current) — `WALLET_ADDR_N` / `WALLET_PRIV_KEY_N` pairs loaded at startup via `config.py`.
2. **Publisher service DB** (planned sync) — The publisher service now stores wallets with encrypted private keys in SQLite via `POST /wallets`. For wallets added through the dashboard, the publisher currently manages the keys. A future enhancement could expose a `GET /wallets/{address}/key` internal endpoint for the signer to fetch keys on-demand, or use a shared secrets manager.

**Current recommendation:** For env-configured wallets, the signer already has the private keys. For DB-managed wallets added via the dashboard, you should also add the corresponding `WALLET_ADDR_N` / `WALLET_PRIV_KEY_N` env vars to the signer service, or implement the sync mechanism described above.

---

## Testing

```bash
python -m pytest tests/signer_service/ -v
```

29 tests cover:
- HMAC consistency between `signer_service` and `user_auth`
- Database CRUD operations and uniqueness constraints
- API validation (invalid address, zero value, 404)
- UUID uniqueness guarantees

---

## Project Structure

```
signer_service/
├── __init__.py
├── app.py              # FastAPI application & endpoints
├── auth_client.py      # HTTP client for user_auth service
├── config.py           # Environment-based configuration
├── database.py         # SQLite DB setup & CRUD
├── main.py             # uvicorn entry-point
├── models.py           # Pydantic request/response schemas
├── requirements.txt    # Python dependencies
├── security.py         # HMAC signing (mirrors user_auth)
└── signer.py           # Core EIP-1559 signing via web3

tests/signer_service/
├── __init__.py
└── test_signer_service.py
```

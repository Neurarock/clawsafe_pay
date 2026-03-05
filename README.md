# ClawSafe Pay

A modular, multi-service payment pipeline for Sepolia testnet ETH transfers
with Telegram-based two-factor approval, **multi-wallet support**, and
prompt-injection protection.

---

## Architecture Overview

```
                    ┌───────────────┐
                    │  OpenClaw /   │
                    │  external     │
                    │  caller       │
                    └──────┬────────┘
                           │  POST /intent  (API-key auth)
                           ▼
                   ┌────────────────┐
                   │  publisher_    │  :8002
                   │  service       │
                   └───┬──────┬─────┘
            build tx   │      │  POST /sign
                       ▼      ▼
          ┌─────────────┐  ┌────────────────┐
          │ transaction │  │  signer_       │  :8001
          │ _builder    │  │  service       │
          │ (library)   │  └───────┬────────┘
          └─────────────┘          │  POST /auth/request
                                   ▼
                           ┌────────────────┐
               ┌───────────│  user_auth     │  :8000
               │  Telegram │  service       │
               │  Bot API  └────────────────┘
               ▼
          ┌───────────┐
          │ Telegram  │  Approve / Reject
          │ user      │  inline keyboard
          └───────────┘
```

### Data Flow

1. **Publisher** receives a `PaymentIntent` from the caller.
2. **Publisher** uses **transaction_builder** (library) to build an unsigned
   EIP-1559 `DraftTx` with a signing digest.
3. **Publisher** optionally sends the `DraftTx` to **reviewer_service**
   (not yet implemented — defaults to `WARN`).
4. **Publisher** submits the tx details to **signer_service** (`POST /sign`).
5. **Signer** requests Telegram approval from **user_auth** (`POST /auth/request`).
6. **User_auth** sends an inline-keyboard prompt to Telegram and polls for the
   user's response.
7. On **Approve**: signer looks up the private key for the requested wallet
   (or falls back to the default), signs the tx, broadcasts it to the Sepolia
   network via `eth_sendRawTransaction`, and returns the on-chain tx hash.
   On **Reject/Expire**: signer reports the status.
8. **Publisher** polls `GET /sign/{tx_id}` until terminal, stores the result.

> **Key principle**: The **signer_service** owns the authentication flow.
> Callers (publisher, future services) never contact user_auth directly —
> they submit to the signer and poll for results.

---

## Services & Ports

| Service              | Default Port | Entry Point                           |
| -------------------- | ------------ | ------------------------------------- |
| **user_auth**        | `8000`       | `python -m user_auth.main`            |
| **signer_service**   | `8001`       | `python -m signer_service.main`       |
| **publisher_service** | `8002`      | `python -m publisher_service.main`    |
| **reviewer_service** | `8003`       | *(reserved — not yet implemented)*    |
| **transaction_builder** | *(library)* | Imported by publisher_service       |

### Multi-Wallet Support

Both the signer and publisher services support **multiple wallets**. Wallets
are configured via numbered environment variables (`WALLET_ADDR_N` /
`WALLET_PRIV_KEY_N`, N = 1–19). Each service exposes a `GET /wallets` endpoint
to list available wallets.

When submitting a payment intent, callers can optionally pass a `from_address`
field to select which wallet signs and pays for the transaction. If omitted,
the default wallet (`SIGNER_FROM_ADDRESS`) is used.

| Endpoint                  | Service   | Auth | Description                                    |
| ------------------------- | --------- | ---- | ---------------------------------------------- |
| `GET /wallets`            | publisher | none | Returns `{"wallets": [...], "default": "0x…"}` |
| `GET /wallets`            | signer    | none | Returns `{"wallets": [...]}`                   |

All ports are configurable via `.env` environment variables.

---

## Quick Start

### Simple demo:

To start service and dashboard:
```bash
bash demo.sh
```
To stop service and dashboard:
```bash
bash demo.sh stop
```

### 1. Prerequisites

- Python 3.11+
- A Telegram bot token (from [@BotFather](https://t.me/BotFather))
- Your Telegram chat ID (use [@userinfobot](https://t.me/userinfobot))
- A Sepolia testnet wallet with some test ETH

### 2. Install Dependencies

```bash
cd clawsafe_pay

# Create a virtual environment (recommended)
python -m venv .venv && source .venv/bin/activate

# Install all service requirements
pip install -r publisher_service/requirements.txt \
            -r signer_service/requirements.txt \
            -r user_auth/requirements.txt

# Install test dependencies
pip install pytest pytest-asyncio respx
```

### 3. Configure `.env`

Copy and edit the `.env` file at the project root:

```dotenv
# ── USER_AUTH SERVICE (port 8000) ─────────────────────────────────
TELEGRAM_BOT_TOKEN=<your-bot-token>
TELEGRAM_CHAT_ID=<your-chat-id>
HMAC_SECRET=<shared-secret>          # generate: python -c "import secrets; print(secrets.token_urlsafe(32))"
AUTH_SERVICE_PORT=8000
SIGNER_SERVICE_CALLBACK_URL=http://localhost:8001/auth/callback

# ── SIGNER SERVICE (port 8001) ───────────────────────────────────
SIGNER_SERVICE_PORT=8001
USER_AUTH_URL=http://localhost:8000

# Multi-wallet: add up to 19 wallet pairs (WALLET_ADDR_N / WALLET_PRIV_KEY_N)
WALLET_ADDR_1=<your-first-wallet-address>
WALLET_PRIV_KEY_1=<first-wallet-private-key>
WALLET_ADDR_2=<your-second-wallet-address>  # optional
WALLET_PRIV_KEY_2=<second-wallet-private-key>
# ... up to WALLET_ADDR_19 / WALLET_PRIV_KEY_19

# ── PUBLISHER SERVICE (port 8002) ────────────────────────────────────
PUBLISHER_SERVICE_PORT=8002
PUBLISHER_API_KEY=<your-api-key>     # callers must send this as X-API-Key header
SIGNER_SERVICE_URL=http://localhost:8001
SIGNER_FROM_ADDRESS=<default-wallet-address>  # default sender if from_address is omitted
SEPOLIA_RPC_URL=https://rpc.sepolia.org
POLICY_RECIPIENT_ALLOWLIST=*         # comma-separated addresses, or * for any

# ── FLOCK / INJECTION FILTER (optional) ──────────────────────────
# FLOCK_API_KEY=<your-flock-key>
```

### 4. Start Services (three terminals)

```bash
# Terminal 1 — user_auth
python -m user_auth.main

# Terminal 2 — signer_service
python -m signer_service.main

# Terminal 3 — publisher_service
python -m publisher_service.main
```

### 5. Delete Telegram Webhook (for local development)

If you previously set a webhook, delete it so the long-polling bot works:

```bash
curl -s -X POST "https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/deleteWebhook"
```

---

## End-to-End Test

### Via publisher_service (full pipeline)

```bash
# Submit a payment intent (uses default wallet)
curl -s -X POST http://localhost:8002/intent \
  -H "Content-Type: application/json" \
  -H "X-API-Key: change-me-publisher-key" \
  -d '{
    "intent_id": "pay-001",
    "from_user": "alice",
    "to_user": "bob",
    "amount_wei": "10000000000000000",
    "to_address": "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045",
    "note": "lunch money"
  }'

# Submit with a specific sender wallet
curl -s -X POST http://localhost:8002/intent \
  -H "Content-Type: application/json" \
  -H "X-API-Key: change-me-publisher-key" \
  -d '{
    "intent_id": "pay-002",
    "from_user": "alice",
    "to_user": "bob",
    "amount_wei": "10000000000000000",
    "to_address": "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045",
    "from_address": "0xd77E4F8142a0C48A62601cD5Be99f591D2D515da",
    "note": "lunch money from wallet 1"
  }'

# List available wallets
curl -s http://localhost:8002/wallets | python -m json.tool

# Response: {"intent_id":"pay-001","status":"pending","message":"Intent received, processing started"}

# Check on Telegram — you should see an approval prompt.
# Tap Approve, then poll:
curl -s http://localhost:8002/intent/pay-001 \
  -H "X-API-Key: change-me-publisher-key" | python -m json.tool
```

### Via signer_service directly (bypass publisher)

```bash
curl -s -X POST http://localhost:8001/sign \
  -H "Content-Type: application/json" \
  -d '{
    "to": "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045",
    "value_wei": "1000000000000000",
    "user_id": "alice",
    "note": "direct test"
  }'

# Returns tx_id — check status:
curl -s http://localhost:8001/sign/<tx_id> | python -m json.tool
```

---

## Running Tests

```bash
# All tests
pytest -v

# Specific service
pytest tests/user_auth/ -v
pytest tests/signer_service/ -v
pytest tests/publisher_service/ -v
pytest tests/transaction_builder/ -v

# Multi-wallet tests
pytest tests/test_multi_wallet.py -v
```

Tests mock all external calls (Telegram API, RPC, inter-service HTTP) — they
run entirely offline with no network dependencies.

---

## Project Structure

```
clawsafe_pay/
├── .env                          # Environment variables (all services)
├── pytest.ini                    # pytest configuration
├── README.md                     # This file
│
├── user_auth/                    # Telegram 2FA auth service (port 8000)
│   ├── app.py                    #   FastAPI endpoints
│   ├── config.py                 #   Environment config
│   ├── database.py               #   SQLite persistence
│   ├── main.py                   #   Uvicorn entry point
│   ├── models.py                 #   Pydantic models
│   ├── security.py               #   HMAC verification
│   ├── signer_callback.py        #   Notify signer of auth result
│   ├── telegram_bot.py           #   Send/edit Telegram messages
│   ├── telegram_handler.py       #   Process callback queries
│   ├── telegram_poller.py        #   Long-polling fallback
│   └── requirements.txt
│
├── signer_service/               # Transaction signer (port 8001)
│   ├── app.py                    #   FastAPI endpoints + background workflow
│   ├── auth_client.py            #   HTTP client for user_auth
│   ├── config.py                 #   Environment config
│   ├── database.py               #   SQLite persistence
│   ├── main.py                   #   Uvicorn entry point
│   ├── models.py                 #   Pydantic models
│   ├── security.py               #   HMAC computation
│   ├── signer.py                 #   EIP-1559 tx signing + broadcast (web3 + eth-account)
│   └── requirements.txt
│
├── publisher_service/            # Payment intent orchestrator (port 8002)
│   ├── app.py                    #   FastAPI endpoints
│   ├── clients.py                #   HTTP clients (reviewer, signer)
│   ├── config.py                 #   Environment config
│   ├── database.py               #   SQLite persistence
│   ├── injection_filter.py       #   Flock API prompt-injection detector
│   ├── main.py                   #   Uvicorn entry point
│   ├── models.py                 #   Pydantic models
│   ├── orchestrator.py           #   Background workflow state machine
│   ├── security.py               #   API-key verification
│   └── requirements.txt
│
├── transaction_builder/          # Unsigned tx construction (library)
│   ├── builder.py                #   build_draft_tx()
│   ├── models.py                 #   PaymentIntent, DraftTx, PolicyConfig
│   ├── policy.py                 #   Pre/post-build policy checks
│   ├── provider.py               #   RPC provider abstraction
│   └── requirements.txt
│
├── dashboard/                    # Self-contained frontend (see dashboard/README.md)
│   ├── index.html                #   Command-center SPA (HTML only)
│   ├── homepage.html             #   Landing page
│   ├── security.html             #   Security architecture page
│   ├── setup_guide.html          #   Setup guide page
│   └── src/                      #   Static assets
│       ├── themes.css            #     Shared theme variables (11 themes)
│       ├── dashboard.css         #     Dashboard-specific styles
│       ├── pages.css             #     Content-page styles
│       ├── theme-loader.js       #     Theme persistence helper
│       └── js/                   #     ES modules (app.js entry point)
│
├── contract_adviser/             # (placeholder — future contract analysis)
├── wallets/                      # (placeholder — future wallet management)
│
└── tests/
    ├── test_multi_wallet.py      # Multi-wallet integration tests
    ├── user_auth/
    │   └── test_user_auth.py
    ├── signer_service/
    │   └── test_signer_service.py
    ├── publisher_service/
    │   ├── conftest.py
    │   ├── test_api.py
    │   ├── test_clients.py
    │   ├── test_injection_filter.py
    │   ├── test_injection_filter_live.py
    │   └── test_orchestrator.py
    └── transaction_builder/
        ├── conftest.py
        ├── test_builder.py
        └── test_policy.py
```

---

## Reviewer Service (Future)

The workflow is designed to support a **reviewer_service** on port `8003`.
When implemented, the reviewer will:

1. Receive `POST /review` with a `DraftTx` and current base fee.
2. Analyze the transaction for anomalies (gas manipulation, suspicious
   recipients, unusual amounts).
3. Return a `ReviewReport` with verdict `OK`, `WARN`, or `BLOCK`.

Currently, if the reviewer is unreachable, the publisher defaults to `WARN`
and continues the workflow. A `BLOCK` verdict halts the pipeline immediately.

---

## Security Notes

- **HMAC-SHA256** authenticates requests between `signer_service ↔ user_auth`.
- **API-key** (`X-API-Key` header) authenticates callers of `publisher_service`.
- **Rate limiting** is applied per-IP on all services (20–30 req/min).
- **Prompt-injection filter** (optional, via Flock API) scores user-controlled
  fields before processing. Score ≥ 8 → request rejected.
- **Private keys** are only loaded by `signer_service` — no other service
  has access to wallet keys. The multi-wallet registry maps each address to
  its private key; the publisher service only stores wallet *addresses*.
- **Terminal states** are immutable — once an intent reaches `confirmed`,
  `rejected`, `expired`, `blocked`, or `failed`, it cannot transition again.
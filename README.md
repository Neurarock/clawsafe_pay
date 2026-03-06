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
   for AI safety analysis (verdict: `OK`, `WARN`, or `BLOCK`).
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
| **reviewer_service** | `8003`       | `python -m reviewer_service.main`     |
| **frontend**         | `8008`       | `python -m frontend.main`             |
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

### API User / Agent Management

Each external caller (bot, agent, integration) receives its own **agent API
key** with granular permission controls. The original `PUBLISHER_API_KEY`
becomes the **admin key** used to manage agents via the dashboard.

| Feature | Description |
| --- | --- |
| **Bot Type & Goal** | Categorise agents (`personal`, `dca_trader`, `spot_trader`, etc.) with a free-text goal |
| **Per-Agent Telegram Chat** | Each agent can route approval prompts to its own Telegram chat ID |
| **Approval Mode** | `always_human`, `auto_within_limits`, or `human_if_above_threshold` |
| **Rolling Window Limits** | `window_limit_wei` + `window_seconds` for sliding-window spend caps |
| **Allowed Contracts** | Restrict which recipient/contract addresses the agent may target |
| **Allowed Assets / Chains** | Token + chain allowlists per agent |
| **Per-Tx & Daily Limits** | `max_amount_wei` and `daily_limit_wei` enforced on `POST /intent` |

> See [docs/api_user_management.md](docs/api_user_management.md) for full API
> reference, dashboard guide, and schema details.

### Telegram Delivery Modes

The `user_auth` service supports two modes for receiving Telegram callback
updates:

| Mode | Config | Behaviour |
| --- | --- | --- |
| **Webhook** (recommended) | `TELEGRAM_WEBHOOK_URL` set in `.env` | Webhook registered automatically on startup. Telegram pushes updates instantly. |
| **Long-polling** (default) | `TELEGRAM_WEBHOOK_URL` empty/unset | Service polls Telegram every few seconds. Works behind NATs. |

Admin endpoints for webhook management:

| Method | Path | Description |
| --- | --- | --- |
| `POST` | `/admin/webhook/register` | Manually register the webhook |
| `DELETE` | `/admin/webhook` | Delete the current webhook |
| `GET` | `/admin/webhook/info` | Show current webhook status |

When webhook mode is active, Telegram callbacks are verified via the
`X-Telegram-Bot-Api-Secret-Token` header using the configured
`TELEGRAM_WEBHOOK_SECRET`.

### Ngrok Single-Tunnel Proxy

For external access (e.g. from a remote OpenClaw agent), expose the
**frontend** port via a single ngrok tunnel:

```bash
ngrok http 8008
```

The frontend automatically proxies requests to internal services:

| Public path | Internal target | Purpose |
| --- | --- | --- |
| `/publisher/*` | `publisher_service:8002` | Payment API |
| `/telegram/*` | `user_auth:8000` | Telegram webhook callbacks |
| `/user-auth/*` | `user_auth:8000` | Admin & health endpoints |
| `/*` | `frontend:8008` | Dashboard, pages, static assets |

Set `TELEGRAM_WEBHOOK_URL=https://<subdomain>.ngrok-free.dev/telegram/webhook`
in `.env` so the user_auth service auto-registers the webhook through the
frontend proxy on startup.

### Reviewer Service

The **reviewer_service** (port 8003) analyses draft transactions using the
**Z.AI GLM** language model for safety assessment before signing:

- Receives `POST /review` with a `DraftTx` and current base fee.
- Analyses the transaction for anomalies (gas manipulation, suspicious
  recipients, unusual amounts).
- Returns a `ReviewReport` with verdict `OK`, `WARN`, or `BLOCK`.

A `BLOCK` verdict halts the pipeline immediately. If the reviewer is
unreachable, the publisher defaults to `WARN` and continues.

### Z.AI & Injection Protection

| Feature | Config | Description |
| --- | --- | --- |
| **Policy Generation** | `ZAI_API_KEY`, `ZAI_API_BASE`, `ZAI_MODEL` | AI-powered policy suggestions for new agents via `POST /api-users/generate-policy` |
| **Policy Chat** | same | Multi-turn policy configuration chat via `POST /api-users/policy-chat` |
| **Agent Instruction Chat** | same | Natural-language tx planning via `POST /agent-instruction` |
| **Tx Review** | same | AI safety review of draft transactions in reviewer_service |
| **Prompt-Injection Filter** | `FLOCK_API_KEY`, `INJECTION_WARN_THRESHOLD`, `INJECTION_BLOCK_THRESHOLD` | Flock API scores user fields; score ≥ block threshold → rejected |

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
pip install -r backend/publisher_service/requirements.txt \
            -r backend/signer_service/requirements.txt \
            -r backend/user_auth/requirements.txt \
            -r frontend/requirements.txt

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

# ── Z.AI LLM (policy generation, tx review, agent instruction) ──
# ZAI_API_KEY=<your-zai-key>            # required for AI features
# ZAI_API_BASE=https://api.z.ai/api/paas/v4
# ZAI_MODEL=glm-5

# ── FLOCK / INJECTION FILTER (optional) ──────────────────────────
# FLOCK_API_KEY=<your-flock-key>
# INJECTION_WARN_THRESHOLD=5            # 0-10 score, warn above this
# INJECTION_BLOCK_THRESHOLD=8           # 0-10 score, block above this

# ── TELEGRAM WEBHOOK (optional — enables instant delivery) ───────
# TELEGRAM_WEBHOOK_URL=https://<subdomain>.ngrok-free.dev/telegram/webhook
# TELEGRAM_WEBHOOK_SECRET=<random-secret>   # verifies Telegram callbacks
```

### 4. Start Services (four terminals)

```bash
# Set PYTHONPATH for backend packages
export PYTHONPATH=backend:$PYTHONPATH

# Terminal 1 — user_auth
python -m user_auth.main

# Terminal 2 — signer_service
python -m signer_service.main

# Terminal 3 — publisher_service
python -m publisher_service.main

# Terminal 4 — frontend
python -m frontend.main
```

### Docker Compose (alternative)

```bash
docker compose up --build
```

### 5. Telegram Delivery

**Option A — Webhook mode (recommended for production / ngrok)**:

Set `TELEGRAM_WEBHOOK_URL` in `.env` and the webhook is auto-registered on
startup. No manual curl required.

```bash
# .env
TELEGRAM_WEBHOOK_URL=https://<subdomain>.ngrok-free.dev/telegram/webhook
```

**Option B — Long-polling (default, no public URL needed)**:

Leave `TELEGRAM_WEBHOOK_URL` empty. Delete any stale webhook if needed:

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
├── demo.sh                       # One-line demo launcher
├── docker-compose.yml            # Docker orchestration
│
├── backend/                      # All backend services & libraries
│   ├── user_auth/                # Telegram 2FA auth service (port 8000)
│   │   ├── app.py                #   FastAPI endpoints
│   │   ├── config.py             #   Environment config
│   │   ├── database.py           #   SQLite persistence
│   │   ├── main.py               #   Uvicorn entry point
│   │   ├── models.py             #   Pydantic models
│   │   ├── security.py           #   HMAC verification
│   │   ├── signer_callback.py    #   Notify signer of auth result
│   │   ├── telegram_bot.py       #   Send/edit Telegram messages
│   │   ├── telegram_handler.py   #   Process callback queries
│   │   ├── telegram_poller.py    #   Long-polling fallback
│   │   ├── telegram_webhook_setup.py  #   Webhook register/delete/info
│   │   ├── Dockerfile
│   │   └── requirements.txt
│   │
│   ├── signer_service/           # Transaction signer (port 8001)
│   │   ├── app.py                #   FastAPI endpoints + background workflow
│   │   ├── auth_client.py        #   HTTP client for user_auth
│   │   ├── config.py             #   Environment config
│   │   ├── database.py           #   SQLite persistence
│   │   ├── main.py               #   Uvicorn entry point
│   │   ├── models.py             #   Pydantic models
│   │   ├── security.py           #   HMAC computation
│   │   ├── signer.py             #   EIP-1559 tx signing + broadcast
│   │   ├── Dockerfile
│   │   └── requirements.txt
│   │
│   ├── publisher_service/        # Payment intent orchestrator (port 8002)
│   │   ├── app.py                #   FastAPI endpoints
│   │   ├── api_users_db.py       #   SQLite persistence (agent management)
│   │   ├── api_user_models.py    #   Pydantic models for agent CRUD
│   │   ├── clients.py            #   HTTP clients (reviewer, signer)
│   │   ├── config.py             #   Environment config
│   │   ├── database.py           #   SQLite persistence (payment intents)
│   │   ├── injection_filter.py   #   Flock API prompt-injection detector
│   │   ├── main.py               #   Uvicorn entry point
│   │   ├── models.py             #   Pydantic models (intents)
│   │   ├── orchestrator.py       #   Background workflow state machine
│   │   ├── security.py           #   API-key verification (admin + agent)
│   │   ├── wallet_models.py      #   Pydantic models for wallet endpoints
│   │   ├── wallets_db.py         #   SQLite persistence (wallet management)
│   │   ├── Dockerfile
│   │   └── requirements.txt
│   │
│   ├── transaction_builder/      # Unsigned tx construction (library)
│   │   ├── builder.py            #   build_draft_tx()
│   │   ├── models.py             #   PaymentIntent, DraftTx, PolicyConfig
│   │   ├── policy.py             #   Pre/post-build policy checks
│   │   ├── provider.py           #   RPC provider abstraction
│   │   └── requirements.txt
│   │
│   ├── chains/                   # Multi-chain support (EVM, Solana, Bitcoin, …)
│   ├── contract_adviser/         # (placeholder — future contract analysis)
│   └── wallets/                  # (placeholder — future wallet management)
│
├── reviewer_service/             # AI transaction reviewer (port 8003)
│   ├── app.py                    #   FastAPI app (POST /review, GET /health)
│   ├── config.py                 #   Environment config (Z.AI settings)
│   ├── llm_client.py             #   Z.AI GLM integration
│   ├── main.py                   #   Uvicorn entry point
│   ├── models.py                 #   ReviewRequest, ReviewReport models
│   └── requirements.txt          #   Python dependencies
│
├── frontend/                     # Dashboard frontend service (port 8008)
│   ├── app.py                    #   FastAPI app + feed proxies
│   ├── config.py                 #   Environment config
│   ├── main.py                   #   Uvicorn entry point
│   ├── Dockerfile
│   ├── requirements.txt          #   Python dependencies
│   ├── index.html                #   Command-center SPA
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
└── tests/
    ├── test_multi_wallet.py      # Multi-wallet integration tests
    ├── frontend/
    │   └── test_pages.py
    ├── user_auth/
    │   └── test_user_auth.py
    ├── signer_service/
    │   └── test_signer_service.py
    ├── publisher_service/
    │   ├── conftest.py
    │   ├── test_api.py
    │   ├── test_api_users.py
    │   ├── test_clients.py
    │   ├── test_injection_filter.py
    │   ├── test_injection_filter_live.py
    │   ├── test_orchestrator.py
    │   ├── test_pages.py
    │   └── test_wallets.py
    └── transaction_builder/
        ├── conftest.py
        ├── test_builder.py
        └── test_policy.py
```

---

## Reviewer Service

The **reviewer_service** is live on port `8003` and integrated into the
transaction pipeline. It uses the **Z.AI GLM** model to analyse draft
transactions before they proceed to signing.

### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/review` | Analyse a `DraftTx`; returns `ReviewReport` with `OK` / `WARN` / `BLOCK` |
| `GET` | `/health` | Health check |

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `REVIEWER_SERVICE_PORT` | `8003` | Listen port |
| `ZAI_API_KEY` | — | Z.AI API key (required) |
| `ZAI_API_BASE` | `https://api.z.ai/api/paas/v4` | Z.AI base URL |
| `ZAI_MODEL` | `glm-5` | Model name |
| `SEPOLIA_RPC_URL` | `https://rpc.sepolia.org` | RPC for on-chain lookups |

If the reviewer is unreachable, the publisher defaults to `WARN`
and continues the workflow. A `BLOCK` verdict halts the pipeline immediately.

---

## Security Notes

- **HMAC-SHA256** authenticates requests between `signer_service ↔ user_auth`.
- **API-key** (`X-API-Key` header) authenticates callers of `publisher_service`.
  The admin key has full access; agent keys are permission-scoped.
  **Only agent keys may submit transactions** (`POST /intent`).
- **Per-agent Telegram routing** — each agent can have its own Telegram chat
  ID for approval prompts, isolated from other agents.
- **Rate limiting** is applied per-IP on publisher_service (600 req/min;
  `/health`, `/docs`, `/openapi.json` exempt).
- **Prompt-injection filter** (optional, via Flock API) scores user-controlled
  fields before processing. Score ≥ `INJECTION_BLOCK_THRESHOLD` (default 8)
  → request rejected; score ≥ `INJECTION_WARN_THRESHOLD` (default 5) → logged.
- **Private keys** are only loaded by `signer_service` — no other service
  has access to wallet keys. The multi-wallet registry maps each address to
  its private key; the publisher service only stores wallet *addresses*.
- **Terminal states** are immutable — once an intent reaches `confirmed`,
  `rejected`, `expired`, `blocked`, or `failed`, it cannot transition again.
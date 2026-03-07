# ClawSafe Pay
*A production-oriented guardrail layer for autonomous on-chain agents.*

> *ClawSafe Pay solves the last-mile problem of agentic AI in finance: not building the AI, but making it safe enough for real people to trust. By enforcing human-in-the-loop approval on every autonomous transaction — with policy limits, AI review, and cryptographic integrity — it opens DeFi-grade financial tools to non-technical users in underserved markets, directly contributing to SDG 10.c's remittance cost reduction target.*

Traditional AI systems advise. Agentic AI systems *execute*. The gap between those two — between a helpful suggestion and an irreversible on-chain transfer — is where trust breaks down. ClawSafe Pay closes that gap by separating **thinking from signing**: agents propose transactions freely, but a segregated control plane — policy enforcement, independent AI safety review, and explicit human approval over Telegram — must clear every intent before a private key is ever used. Teams get a practical way to ship agentic finance with accountable controls instead of blind automation.

---

## UN SDG Impact

### Primary: SDG 10 — Reduced Inequalities (Target 10.c)
> *"Reduce to less than 3% the transaction costs of migrant remittances and eliminate remittance corridors with costs higher than 5%"*

1.4 billion adults are unbanked. Migrant remittances through Western Union or MoneyGram cost 5–10%. Crypto reduces this to <0.1% — but adoption stalls on trust: people don't delegate fund movement to software they don't understand. ClawSafe Pay attacks this barrier directly. An AI agent executes the payment; policy guardrails enforce limits; the human approves in plain English via Telegram before anything broadcasts. A person with zero crypto knowledge can delegate to an AI agent that acts within pre-approved parameters — safely.

### Secondary: SDG 8 — Decent Work and Economic Growth (Target 8.10)
DCA bots, micro-lending interactions, automated payroll — these DeFi-grade tools are currently locked behind technical expertise. ClawSafe Pay's per-agent policy and human-in-the-loop approval makes them safely delegatable to AI, extending economic tooling to non-technical actors at near-zero marginal cost.

### Third: SDG 16 — Peace, Justice and Strong Institutions (Target 16.6)
The regulatory concern with agentic AI in finance is accountability. ClawSafe Pay gives a concrete answer: every intent carries an immutable audit trail, the reviewer produces a documented verdict, the human explicitly approves, and the digest consistency check ensures what was reviewed is exactly what was signed. This is the accountability infrastructure that makes AI financial agents governable.

### Infrastructure: SDG 9 — Industry, Innovation and Infrastructure
Agentic financial execution requires a new class of infrastructure — not wallets, not exchanges, but trust layers. ClawSafe Pay's multi-service architecture (HMAC auth, cryptographic digests, AI safety review, prompt-injection filtering) is that layer: open-source, composable, deployable anywhere.

---

## Hackathon Tracks

### FLock Track — Agentic AI for SDGs

**OpenClaw integration:** ClawSafe Pay exposes a published OpenClaw skill (`SKILL_CLAWSAFEPAY.md`) with four endpoints: submit intent, poll status, list intents, list wallets. Any OpenClaw agent can delegate fund movement to ClawSafe Pay with a single API call.

**FLock API usage:** The publisher service runs every incoming payment intent through a **prompt-injection filter** powered by the [FLock API](https://platform.flock.io/models) (`backend/publisher_service/injection_filter.py`). User-controlled fields (`from_user`, `to_user`, `note`, `intent_id`) are scored 0–10 for injection patterns — jailbreaks, role-play directives, system-prompt overrides. Score ≥ block threshold → request rejected before it ever reaches the AI stack. This protects the downstream Z.AI reviewer from adversarial inputs embedded in agent payloads.

**Open-source models only:** All LLM inference uses open-source models via FLock's inference API and Z.AI's GLM series — no proprietary model vendors.

**Multi-channel deployment:** Telegram is the human approval channel. Every pending transaction surfaces as an inline-keyboard prompt (`Approve` / `Reject`), delivered via webhook (recommended) or long-polling. Each agent can route to its own dedicated Telegram chat ID.

---

### Z.AI Track — Production-Ready AI Agents

Z.AI's **GLM series** is a core, non-optional component of ClawSafe Pay. It powers three distinct parts of the system:

| Feature | Service | File | What Z.AI GLM Does |
|---|---|---|---|
| **Transaction Safety Review** | `reviewer_service` | `llm_client.py` | Analyses every draft transaction for gas manipulation, suspicious recipients, unusual amounts, and calldata mismatches. Returns `OK` / `WARN` / `BLOCK`. Logs model name + request_id as proof. |
| **Policy Generation** | `publisher_service` | `zai_policy_client.py` | When an admin creates a new agent, GLM suggests an optimal spending policy (approval mode, limits, allowed contracts) based on the bot's stated purpose. |
| **Agentic Transaction Planning** | `publisher_service` | `zai_instruction_client.py` | Accepts natural-language instructions ("buy WBTC with 0.005 ETH on Uniswap"), resolves wallet balances and recent trade history, and outputs a structured `PaymentIntent` via a `plan_transaction` tool call. |

The reviewer falls back to deterministic heuristics if Z.AI is unavailable, keeping the pipeline live at all times.

---

### Animoca Minds Track — Multi-Agent Systems

ClawSafe Pay is a **coordinated swarm of five specialized agents**, each owning a distinct cognitive layer:

```
┌─────────────────────────────────────────────────────────┐
│                  MULTI-AGENT ARCHITECTURE               │
│                                                         │
│  OpenClaw Agent (external)                              │
│       │  POST /intent (X-API-Key)                       │
│       ▼                                                 │
│  ① Publisher Agent       :8002  ─── orchestrates ───►  │
│       │                                                 │
│       ├──► ② Transaction Builder   (library)            │
│       │        builds unsigned EIP-1559 tx + digest     │
│       │                                                 │
│       ├──► ③ Reviewer Agent        :8003                │
│       │        Z.AI GLM safety review → OK/WARN/BLOCK   │
│       │                                                 │
│       └──► ④ Signer Agent          :8001                │
│                 ▼                                       │
│            ⑤ Auth Agent            :8000                │
│                 ▼                                       │
│            Telegram (human) → Approve / Reject          │
│                 ▼                                       │
│            eth_sendRawTransaction → Sepolia             │
└─────────────────────────────────────────────────────────┘
```

Each agent has **identity** (API key, Telegram chat ID, wallet address), **memory** (SQLite — payment history, agent profiles, approval records), and **cognition** (Z.AI GLM for reasoning, Flock API for adversarial filtering, HMAC for inter-agent trust). No agent has more authority than its role requires — the signer never speaks to user_auth except through the defined contract; the publisher never holds private keys.

---

## Architecture & Data Flow

1. **Publisher** receives a `PaymentIntent` from an OpenClaw agent.
2. **Publisher** runs user-controlled fields through the **Flock API injection filter**.
3. **Transaction Builder** (library, no HTTP) constructs an unsigned EIP-1559 `DraftTx` and computes its signing digest via `keccak256(0x02 || rlp([...]))`.
4. **Reviewer** (Z.AI GLM-5) analyses the `DraftTx` — gas ratios, recipient, calldata decoding — and returns a verdict.
5. **Publisher** verifies the digest is unchanged from what the reviewer evaluated (security invariant).
6. **Signer** receives the draft, requests Telegram approval from **user_auth** via HMAC-signed callback.
7. **User_auth** sends an inline-keyboard prompt to Telegram and waits.
8. On **Approve**: signer signs with the appropriate private key and broadcasts via `eth_sendRawTransaction`. On **Reject / Expire**: pipeline terminates.
9. **Publisher** polls signer until confirmed, stores the result.

> **Key principle:** The signer_service owns the authentication flow. The publisher never contacts user_auth directly — it submits to the signer and polls for results. Private keys never leave the signer.

### State Machine

```
pending → building → reviewing → [BLOCK: blocked]
                              → awaiting_approval → [reject/expire: rejected/expired]
                                                  → signing → broadcast → confirmed
                                                                        → failed
```

---

## Services & Ports

| Service | Port | Responsibility |
|---|---|---|
| `publisher_service` | 8002 | Orchestrator: intent intake, policy enforcement, state machine |
| `signer_service` | 8001 | EIP-1559 signing, multi-wallet management, auth flow ownership |
| `user_auth` | 8000 | Telegram 2FA: send approval prompt, receive callback, notify signer |
| `reviewer_service` | 8003 | Z.AI GLM safety review: gas, recipients, calldata analysis |
| `frontend` | 8008 | Dashboard SPA + API proxy (single ngrok tunnel entry point) |
| `transaction_builder` | *(library)* | Unsigned tx construction, digest computation, policy validation |

### Multi-Wallet Support

Up to 19 sender wallets configured via `WALLET_ADDR_N` / `WALLET_PRIV_KEY_N` (N = 1–19). Callers pass `from_address` in the intent to select a wallet; if omitted, the default (`SIGNER_FROM_ADDRESS`) is used.

| Endpoint | Service | Description |
|---|---|---|
| `GET /wallets` | publisher | `{"wallets": [...], "default": "0x…"}` |
| `GET /wallets` | signer | `{"wallets": [...]}` |

### Per-Agent Policy Controls

Each OpenClaw agent gets its own API key with granular permissions. The admin key (`PUBLISHER_API_KEY`) manages agents but cannot submit transactions.

| Feature | Description |
|---|---|
| **Bot Type & Goal** | `personal`, `dca_trader`, `spot_trader`, `nft_sniper`, etc. + free-text goal |
| **Approval Mode** | `always_human`, `auto_within_limits`, `human_if_above_threshold` |
| **Per-Tx & Daily Limits** | `max_amount_wei`, `daily_limit_wei` |
| **Rolling Window** | `window_limit_wei` + `window_seconds` sliding-window spend cap |
| **Allowed Contracts** | Recipient/contract address allowlist per agent |
| **Allowed Assets / Chains** | Token + chain allowlists |
| **Per-Agent Telegram Chat** | Approval prompts route to agent-specific chat ID |

Z.AI-powered policy generation: `POST /api-users/generate-policy` describes the bot and GLM suggests an optimal policy. Multi-turn refinement via `POST /api-users/policy-chat`.

See [docs/api_user_management.md](docs/api_user_management.md) for full API reference.

### Ngrok Single-Tunnel Proxy

```bash
ngrok http 8008
```

| Public path | Internal target |
|---|---|
| `/publisher/*` | `publisher_service:8002` |
| `/telegram/*` | `user_auth:8000` (Telegram webhook callbacks) |
| `/user-auth/*` | `user_auth:8000` (admin endpoints) |
| `/*` | `frontend:8008` (dashboard, static assets) |

Set `TELEGRAM_WEBHOOK_URL=https://<subdomain>.ngrok-free.dev/telegram/webhook` in `.env` to auto-register the webhook on startup.

---

## Quick Start

### One-line demo

```bash
bash demo.sh       # start all services + dashboard
bash demo.sh stop  # stop everything
```

### Docker Compose

```bash
docker compose up --build
```

### Manual setup

**1. Prerequisites**

- Python 3.11+
- Telegram bot token (from [@BotFather](https://t.me/BotFather))
- Telegram chat ID (from [@userinfobot](https://t.me/userinfobot))
- Sepolia wallet with test ETH
- Z.AI API key (for reviewer + policy features)
- Flock API key (for injection filter)

**2. Install dependencies**

```bash
python -m venv .venv && source .venv/bin/activate

pip install -r backend/publisher_service/requirements.txt \
            -r backend/signer_service/requirements.txt \
            -r backend/user_auth/requirements.txt \
            -r backend/reviewer_service/requirements.txt \
            -r frontend/requirements.txt

pip install pytest pytest-asyncio respx  # for tests
```

**3. Configure `.env`**

```dotenv
# ── Telegram ──────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN=<your-bot-token>
TELEGRAM_CHAT_ID=<your-chat-id>
HMAC_SECRET=<32-byte-hex>              # python -c "import secrets; print(secrets.token_hex(32))"

# ── Wallets (up to 19 pairs) ──────────────────────────────────────────
WALLET_ADDR_1=<checksum-address>
WALLET_PRIV_KEY_1=<private-key>
SIGNER_FROM_ADDRESS=<default-wallet>   # used when from_address is omitted

# ── RPC ──────────────────────────────────────────────────────────────
SEPOLIA_RPC_URL=https://rpc.sepolia.org

# ── Publisher ─────────────────────────────────────────────────────────
PUBLISHER_API_KEY=<admin-key>
POLICY_RECIPIENT_ALLOWLIST=*           # comma-separated addresses, or * for any

# ── Z.AI (reviewer, policy generation, agent instruction) ─────────────
ZAI_API_KEY=<your-zai-key>
ZAI_API_BASE=https://api.z.ai/api/paas/v4
ZAI_MODEL=glm-5

# ── Flock API (prompt-injection filter) ──────────────────────────────
FLOCK_API_KEY=<your-flock-key>
INJECTION_WARN_THRESHOLD=5
INJECTION_BLOCK_THRESHOLD=7

# ── Telegram Webhook (recommended) ───────────────────────────────────
TELEGRAM_WEBHOOK_URL=https://<subdomain>.ngrok-free.dev/telegram/webhook
TELEGRAM_WEBHOOK_SECRET=<random-secret>
```

**4. Start services**

```bash
export PYTHONPATH=backend:$PYTHONPATH

python -m user_auth.main          # terminal 1  :8000
python -m signer_service.main     # terminal 2  :8001
python -m publisher_service.main  # terminal 3  :8002
python -m reviewer_service.main   # terminal 4  :8003
python -m frontend.main           # terminal 5  :8008
```

---

## End-to-End Test

```bash
# Submit a payment intent
curl -s -X POST http://localhost:8002/intent \
  -H "Content-Type: application/json" \
  -H "X-API-Key: <your-agent-key>" \
  -d '{
    "intent_id": "pay-001",
    "from_user": "alice",
    "to_user": "bob",
    "amount_wei": "10000000000000000",
    "to_address": "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045",
    "note": "lunch money"
  }'

# → Check Telegram — tap Approve, then poll:
curl -s http://localhost:8002/intent/pay-001 \
  -H "X-API-Key: <your-agent-key>" | python -m json.tool

# List available wallets
curl -s http://localhost:8002/wallets | python -m json.tool

# Use a specific sender wallet
curl -s -X POST http://localhost:8002/intent \
  -H "Content-Type: application/json" \
  -H "X-API-Key: <your-agent-key>" \
  -d '{
    "intent_id": "pay-002",
    "from_user": "alice",
    "to_user": "carol",
    "amount_wei": "5000000000000000",
    "to_address": "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045",
    "from_address": "0xd77E4F8142a0C48A62601cD5Be99f591D2D515da"
  }'
```

---

## Publisher API Reference

| Method | Path | Auth | Description |
|---|---|---|---|
| `POST` | `/intent` | Agent key | Submit a payment intent |
| `GET` | `/intent/{id}` | Agent key | Poll intent status |
| `GET` | `/intents` | Agent key | List all intents |
| `GET` | `/wallets` | None | List available wallets |
| `GET` | `/health` | None | Health check |
| `POST` | `/api-users` | Admin | Create agent |
| `GET` | `/api-users` | Admin | List agents |
| `PUT` | `/api-users/{id}` | Admin | Update agent |
| `DELETE` | `/api-users/{id}` | Admin | Delete agent |
| `POST` | `/api-users/{id}/regenerate-key` | Admin | Regenerate API key |
| `POST` | `/api-users/generate-policy` | Admin | Z.AI policy suggestion |
| `POST` | `/api-users/policy-chat` | Admin | Multi-turn policy refinement |
| `POST` | `/agent-instruction` | Agent | Natural-language tx planning (Z.AI) |

### Reviewer API

| Method | Path | Description |
|---|---|---|
| `POST` | `/review` | Analyse a `DraftTx`; returns `ReviewReport` with `OK`/`WARN`/`BLOCK` |
| `GET` | `/health` | Health check |

---

## Security Architecture

| Mechanism | Where | What it does |
|---|---|---|
| **HMAC-SHA256** | `signer ↔ user_auth` | Constant-time `hmac.compare_digest` over `request_id:user_id:action` |
| **API Keys (Admin/Agent)** | `X-API-Key` header | Admin: manage agents only. Agent: submit intents only, within scoped policy |
| **Prompt-Injection Filter** | `publisher_service/injection_filter.py` | Flock API scores 0–10; ≥ block threshold → rejected before AI stack |
| **Digest Consistency Check** | `publisher_service/orchestrator.py` | Security invariant: digest at review time must equal digest at signing time |
| **Anti-Replay** | `user_auth/database.py` | Duplicate `request_id` → 409 |
| **Request Expiry** | `user_auth` | Pending approvals expire after `AUTH_REQUEST_TTL_SECONDS` (default 300s) |
| **Rate Limiting** | `publisher_service` | 600 req/min per IP |
| **Private Key Isolation** | `signer_service` only | No other service ever loads wallet private keys |
| **Terminal State Immutability** | `publisher_service/database.py` | `confirmed`, `rejected`, `expired`, `blocked`, `failed` cannot re-transition |
| **Per-Agent Telegram Routing** | publisher + user_auth | Each agent's approvals go to its own isolated chat ID |

---

## Multi-Chain Architecture

ClawSafe Pay uses a **chain registry** (`backend/chains/registry.py`) that decouples the payment pipeline from any specific chain. Sepolia is fully operational; the registry is extensible to any chain family.

| Chain | Status | Notes |
|---|---|---|
| **Sepolia (EVM)** | ✅ Live | EIP-1559, multi-wallet, fully tested |
| **Base L2** | Config ready | Shares EVM implementation; needs `BASE_RPC_URL` |
| Solana | Placeholder | Interface defined, implementation pending |
| Bitcoin | Placeholder | UTXO model; interface defined |
| Zcash | Placeholder | Interface defined |
| Cardano | Placeholder | eUTxO model; interface defined |

---

## Running Tests

```bash
export PYTHONPATH=backend:$PYTHONPATH

# Full suite
python3 -m pytest tests/ -v

# By service
python3 -m pytest tests/transaction_builder/ -v   # 46 tests, all passing
python3 -m pytest tests/test_multi_wallet.py -v
python3 -m pytest tests/user_auth/ -v
python3 -m pytest tests/signer_service/ -v
python3 -m pytest tests/publisher_service/ -v
```

All tests mock external calls (Telegram API, Sepolia RPC, Z.AI, Flock) — fully offline, no network dependencies.

---

## Project Structure

```
clawsafe_pay/
├── .env                          # All service configuration
├── docker-compose.yml            # Five-service orchestration
├── demo.sh                       # One-line demo launcher
├── SKILL_CLAWSAFEPAY.md         # OpenClaw agent skill definition
│
├── backend/
│   ├── publisher_service/        # Orchestrator (port 8002)
│   │   ├── orchestrator.py       #   Async state machine
│   │   ├── injection_filter.py   #   Flock API prompt-injection scoring
│   │   ├── zai_policy_client.py  #   Z.AI policy generation + chat
│   │   ├── zai_instruction_client.py # Z.AI agentic tx planning
│   │   ├── api_users_db.py       #   Per-agent key & policy management
│   │   └── security.py           #   Admin vs agent key separation
│   │
│   ├── reviewer_service/         # Z.AI safety reviewer (port 8003)
│   │   └── llm_client.py         #   GLM-5 analysis: gas, recipients, calldata
│   │
│   ├── signer_service/           # EIP-1559 signer (port 8001)
│   │   ├── signer.py             #   Multi-chain signing + broadcast
│   │   └── auth_client.py        #   Owns the user_auth flow
│   │
│   ├── user_auth/                # Telegram 2FA (port 8000)
│   │   ├── telegram_bot.py       #   Send/edit inline-keyboard prompts
│   │   ├── telegram_webhook_setup.py
│   │   └── signer_callback.py    #   Notify signer of approval result
│   │
│   ├── transaction_builder/      # Unsigned tx library (no HTTP)
│   │   ├── builder.py            #   build_draft_tx() + EIP-1559 digest
│   │   └── policy.py             #   Pre/post-build policy validation
│   │
│   └── chains/                   # Multi-chain registry
│       ├── registry.py           #   ChainRegistration lookup by chain_id
│       ├── evm/sepolia/          #   ✅ Live: EVMProvider, Builder, Signer
│       ├── evm/base_l2/          #   Config ready
│       ├── solana/               #   Placeholder
│       ├── bitcoin/              #   Placeholder
│       └── cardano/ zcash/       #   Placeholders
│
├── frontend/                     # Dashboard SPA + proxy (port 8008)
│   ├── app.py                    #   FastAPI + /publisher/* and /telegram/* proxies
│   ├── index.html                #   Command-center dashboard
│   └── api_users.html            #   Agent management UI
│
├── docs/
│   ├── publisher_service_spec.md # Full state machine & API spec
│   └── api_user_management.md   # Agent key system reference
│
└── tests/                        # 102 tests; offline, mocked externals
    ├── transaction_builder/      # 46 passing
    ├── test_multi_wallet.py
    ├── publisher_service/
    ├── signer_service/
    └── user_auth/
```

---

## Environment Variables Reference

| Variable | Service | Description |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | user_auth | Bot token from @BotFather |
| `TELEGRAM_CHAT_ID` | user_auth | Default approval chat ID |
| `TELEGRAM_WEBHOOK_URL` | user_auth | Enables webhook mode (recommended) |
| `TELEGRAM_WEBHOOK_SECRET` | user_auth | Verifies Telegram callback header |
| `HMAC_SECRET` | signer, user_auth | Shared 32-byte secret for inter-service auth |
| `WALLET_ADDR_N` / `WALLET_PRIV_KEY_N` | signer | Multi-wallet pairs (N = 1–19) |
| `SIGNER_FROM_ADDRESS` | signer | Default wallet when `from_address` omitted |
| `SEPOLIA_RPC_URL` | signer, reviewer | Sepolia JSON-RPC endpoint |
| `PUBLISHER_API_KEY` | publisher | Admin key — manages agents, cannot submit intents |
| `POLICY_RECIPIENT_ALLOWLIST` | publisher | `*` or comma-separated addresses |
| `ZAI_API_KEY` | reviewer, publisher | Z.AI API key |
| `ZAI_API_BASE` | reviewer, publisher | Default: `https://api.z.ai/api/paas/v4` |
| `ZAI_MODEL` | reviewer, publisher | Default: `glm-5` |
| `FLOCK_API_KEY` | publisher | Flock API key for injection filter |
| `INJECTION_WARN_THRESHOLD` | publisher | Score ≥ this → log warning (default 5) |
| `INJECTION_BLOCK_THRESHOLD` | publisher | Score ≥ this → reject request (default 7) |
| `AUTH_REQUEST_TTL_SECONDS` | user_auth | Approval expiry window (default 300) |

# Publisher Service — Agent Implementation Spec

**Port:** 8002
**Language:** Python 3.9+, FastAPI, SQLite (same stack as `user_auth`)
**Location:** `publisher_service/`

---

## What This Service Does

The publisher service is the **orchestration hub** of ClawSafe Pay. It:

1. Receives a `PaymentIntent` from an OpenClaw agent via HTTP
2. Builds an unsigned EIP-1559 `DraftTx` (using the `transaction_builder` module in this repo)
3. Sends the draft to `reviewer_service` for safety evaluation
4. If the reviewer does not BLOCK, forwards an auth request to `user_auth` (Telegram approval)
5. Polls for approval; on approval, sends the signed request to `signer_service`
6. Tracks state through all transitions in SQLite and exposes status for polling

**It does not hold private keys, sign transactions, or perform LLM calls.** Those are the signer and reviewer's jobs.

---

## File Structure to Create

```
publisher_service/
├── __init__.py
├── app.py          # FastAPI app, routes, lifespan
├── config.py       # env-var config (mirrors user_auth/config.py style)
├── database.py     # SQLite setup + CRUD
├── models.py       # Pydantic request/response models
├── orchestrator.py # Core async workflow logic
├── clients.py      # HTTP clients for reviewer, user_auth, signer
├── security.py     # API key verification for incoming requests
└── requirements.txt
```

---

## Configuration (`config.py`)

Load from `.env` at the project root (same as `user_auth/config.py`). Required env vars:

```dotenv
# Service
PUBLISHER_SERVICE_PORT=8002

# Downstream services
REVIEWER_SERVICE_URL=http://localhost:8003
USER_AUTH_SERVICE_URL=http://localhost:8000
SIGNER_SERVICE_URL=http://localhost:8001

# Shared secrets
HMAC_SECRET=<same value as user_auth>        # used to sign auth requests to user_auth
PUBLISHER_API_KEY=<random 32-byte hex>        # OpenClaw presents this to call this service

# Signer wallet
SIGNER_FROM_ADDRESS=0x<wallet address>        # used for nonce lookup in tx builder

# Policy overrides (optional, all have defaults in PolicyConfig)
POLICY_MAX_AMOUNT_WEI=50000000000000000
POLICY_RECIPIENT_ALLOWLIST=0xADDR1,0xADDR2   # comma-separated; use * for any
POLICY_TIP_WEI=1500000000

# Approval polling
APPROVAL_POLL_INTERVAL_SECONDS=3
APPROVAL_TIMEOUT_SECONDS=120
```

---

## Database Schema (`database.py`)

Single SQLite file: `publisher_service/intents.db`

### Table: `payment_intents`

| Column | Type | Description |
|--------|------|-------------|
| `intent_id` | TEXT PK | UUID from caller |
| `from_user` | TEXT | Payer identifier |
| `to_user` | TEXT | Payee identifier |
| `to_address` | TEXT | Recipient EVM address |
| `amount_wei` | TEXT | Transfer amount (decimal string) |
| `note` | TEXT | Memo |
| `status` | TEXT | See state machine below |
| `created_at` | TEXT | ISO-8601 UTC |
| `updated_at` | TEXT | ISO-8601 UTC |
| `draft_tx_json` | TEXT | JSON-serialised `DraftTx` (nullable) |
| `review_report_json` | TEXT | JSON-serialised `ReviewReport` (nullable) |
| `auth_request_id` | TEXT | Forwarded to `user_auth` (nullable) |
| `tx_hash` | TEXT | Broadcast tx hash (nullable) |
| `error_message` | TEXT | Last error string (nullable) |

### State Machine

```
pending → building → reviewing → awaiting_approval → signing → broadcast → confirmed
                                                             ↘
                                              rejected / expired / blocked / failed
```

Terminal states: `confirmed`, `rejected`, `expired`, `blocked`, `failed`

**Transitions:**
- `pending` → `building`: immediately on receipt (background task started)
- `building` → `reviewing`: `DraftTx` successfully constructed
- `building` → `failed`: tx builder raised `PolicyError` or `ProviderError`
- `reviewing` → `awaiting_approval`: reviewer returned OK or WARN
- `reviewing` → `blocked`: reviewer returned BLOCK verdict
- `awaiting_approval` → `signing`: user approved in Telegram
- `awaiting_approval` → `rejected`: user rejected in Telegram
- `awaiting_approval` → `expired`: approval TTL elapsed (120s)
- `signing` → `broadcast`: signer returned tx_hash
- `signing` → `failed`: signer returned error
- `broadcast` → `confirmed`: (can be immediate for MVP, or polled)

**Why the terminal states are split** — each means something different to the polling agent:
- `blocked`: policy/safety decision — do not retry without changing the intent
- `rejected`: user said no — may retry if user changes their mind
- `expired`: timeout — safe to retry with a fresh intent
- `failed`: technical error — check `error_message`, may be transient

**Future caveats (do not implement for MVP)**

1. **Signer idempotency on crash.** If the service crashes in `signing` state, a naive restart would call the signer again on the same nonce. The signer should return the existing `tx_hash` if called twice with the same `intent_id` rather than re-signing.

2. **`broadcast` vs `confirmed` are collapsed for MVP.** In production, hold at `broadcast` and poll the chain until the tx appears in a block before moving to `confirmed`. A tx can be dropped from the mempool if gas spikes after broadcast.

3. **Gas staleness / rebuild loop.** If gas rises significantly while in `awaiting_approval`, the current digest becomes expensive or stuck. Future fix: add a `rebuilding` transition (`awaiting_approval → building`) that fetches fresh gas, produces a new digest, and re-prompts the user. Not needed on Sepolia testnet.

---

## API Endpoints

### `POST /intent`

Receive a new payment intent from OpenClaw. Starts processing asynchronously.

**Auth:** `X-API-Key: <PUBLISHER_API_KEY>` header required. Return 401 if missing or wrong.

**Request body:**
```json
{
  "intent_id": "550e8400-e29b-41d4-a716-446655440000",
  "from_user": "userA",
  "to_user": "userB",
  "chain": "sepolia",
  "asset": "ETH",
  "amount_wei": "10000000000000000",
  "to_address": "0xd8da6bf26964af9d7eed9e03e53415d37aa96045",
  "note": "lunch"
}
```

**Response 202 (accepted):**
```json
{
  "intent_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "pending",
  "message": "Intent received, processing started"
}
```

**Errors:**
- `401` — missing/invalid API key
- `409` — duplicate `intent_id`
- `422` — Pydantic validation failure (bad address, non-integer amount, etc.)

**Implementation note:** Store the intent immediately, return 202, then launch the full workflow in an `asyncio.create_task`. The caller polls `GET /intent/{id}` for updates.

---

### `GET /intent/{intent_id}`

Poll the current state of an intent.

**Auth:** Same `X-API-Key` header.

**Response 200:**
```json
{
  "intent_id": "...",
  "status": "awaiting_approval",
  "from_user": "userA",
  "to_user": "userB",
  "to_address": "0x...",
  "amount_wei": "10000000000000000",
  "note": "lunch",
  "created_at": "2026-03-03T12:00:00+00:00",
  "updated_at": "2026-03-03T12:00:05+00:00",
  "draft_tx": { ... },          // present once built
  "review_report": { ... },     // present once reviewed
  "tx_hash": null,              // present once broadcast
  "error_message": null         // present on failure
}
```

**Errors:** `404` if not found.

---

### `GET /health`

Returns `{"status": "ok"}`. No auth required.

---

## Orchestration Workflow (`orchestrator.py`)

This is the core of the service. Implement as a single async function `run_intent_workflow(intent_id: str)` that steps through the state machine:

```python
async def run_intent_workflow(intent_id: str) -> None:
    ...
```

### Step 1 — Build DraftTx

```python
from transaction_builder import build_draft_tx, PolicyConfig, PolicyError, ProviderError, Web3Provider

policy = PolicyConfig(
    recipient_allowlist=config.POLICY_RECIPIENT_ALLOWLIST,
    max_amount_wei=config.POLICY_MAX_AMOUNT_WEI,
    tip_wei=config.POLICY_TIP_WEI,
)
provider = Web3Provider(config.SEPOLIA_RPC_URL)

try:
    db.update_status(intent_id, "building")
    draft = await build_draft_tx(intent, provider, config.SIGNER_FROM_ADDRESS, policy)
    db.store_draft_tx(intent_id, draft)
    db.update_status(intent_id, "reviewing")
except PolicyError as e:
    db.update_status(intent_id, "failed", error=f"Policy violation: {e.reason}")
    return
except ProviderError as e:
    db.update_status(intent_id, "failed", error=f"Provider error: {e}")
    return
```

### Step 2 — Call Reviewer

POST to `reviewer_service` at `POST /review`:

**Request:**
```json
{
  "intent_id": "...",
  "draft_tx": { <DraftTx fields> },
  "current_base_fee_wei": 10000000000
}
```

**Expected response (`ReviewReport`):**
```json
{
  "intent_id": "...",
  "digest": "0x...",
  "verdict": "OK",                    // "OK" | "WARN" | "BLOCK"
  "reasons": [],
  "summary": "Transfer looks normal.",
  "gas_assessment": {
    "estimated_total_fee_wei": "441000000000000",
    "is_reasonable": true,
    "reference": "within 1.5x current estimate"
  },
  "model_used": "zai-glm-4"
}
```

Handling:
- `BLOCK` → store report, set status `blocked`, return
- `OK` or `WARN` → continue to approval
- HTTP error / timeout → set status `failed`, return

**Consistency check (important):** Before proceeding, verify that `review_report.digest == draft_tx.digest`. If they differ, abort with `failed` status and log a tamper alert. This is a key security invariant.

### Step 3 — Request Telegram Approval

POST to `user_auth` at `POST /auth/request`.

The `action` field must encode the key tx parameters so the user sees them in Telegram:

```python
action = (
    f"Pay {intent.amount_wei} wei ({int(intent.amount_wei)/1e18:.6f} ETH) "
    f"to {draft.to} on Sepolia | "
    f"Gas: {draft.gas_limit} × {int(draft.max_fee_per_gas)//1_000_000_000} gwei | "
    f"Reviewer: {review.verdict} | "
    f"Digest: {draft.digest[:10]}…{draft.digest[-6:]}"
)
```

The `request_id` for `user_auth` must include the `intent_id` so you can correlate it:
```python
auth_request_id = f"{intent_id}:{uuid4()}"
```

Sign with HMAC as `user_auth` expects (use the same `security.py` pattern from `user_auth`).

Store `auth_request_id` in the DB. Set status to `awaiting_approval`.

### Step 4 — Poll for Approval

Poll `GET /auth/{auth_request_id}` every `APPROVAL_POLL_INTERVAL_SECONDS` until:
- `status == "approved"` → proceed to signing
- `status == "rejected"` → set intent status `rejected`, return
- `status == "expired"` → set intent status `expired`, return
- Total elapsed > `APPROVAL_TIMEOUT_SECONDS` → set `expired`, return

### Step 5 — Call Signer

POST to `signer_service` at `POST /sign`:

```json
{
  "intent_id": "...",
  "digest": "0x...",
  "draft_tx": { <full DraftTx> },
  "auth_request_id": "..."
}
```

**Consistency check:** The signer will independently re-derive the digest from `draft_tx` fields and verify it matches the `digest` field. The publisher must send both so the signer can validate. If they mismatch, the signer will reject — treat any 4xx from signer as `failed`.

Expected response:
```json
{
  "tx_hash": "0x...",
  "signed_at": "2026-03-03T12:01:30+00:00"
}
```

On success: store `tx_hash`, set status `broadcast` (then `confirmed` for MVP — no need to poll chain).
On error: set status `failed`.

---

## HTTP Clients (`clients.py`)

Create three async HTTP clients using `httpx.AsyncClient`:

```python
async def call_reviewer(draft_tx: DraftTx, current_base_fee_wei: int) -> ReviewReport: ...
async def request_auth(intent_id, user_id, action, hmac_digest) -> str: ...  # returns request_id
async def poll_auth_status(auth_request_id: str) -> str: ...                 # returns status string
async def call_signer(intent_id, digest, draft_tx, auth_request_id) -> str:  # returns tx_hash
```

All clients should:
- Set a 10-second connect timeout, 30-second read timeout
- On any non-2xx response, raise a descriptive exception (don't silently fail)
- Log the full URL + status code on every call (for audit trail)

---

## Security (`security.py`)

```python
def verify_api_key(provided: str) -> bool:
    """Constant-time comparison against PUBLISHER_API_KEY."""
    import hmac
    expected = config.PUBLISHER_API_KEY.encode()
    return hmac.compare_digest(provided.encode(), expected)
```

Use as a FastAPI dependency:
```python
from fastapi import Header, HTTPException

async def require_api_key(x_api_key: str = Header(...)):
    if not verify_api_key(x_api_key):
        raise HTTPException(status_code=401, detail="Invalid API key")
```

Apply to all routes except `/health`.

---

## Models (`models.py`)

Define these Pydantic models (import and reuse `PaymentIntent` and `DraftTx` from `transaction_builder.models`):

```python
from transaction_builder.models import PaymentIntent, DraftTx  # re-use directly

class IntentResponse(BaseModel):
    intent_id: str
    status: str
    message: str

class IntentStatusResponse(BaseModel):
    intent_id: str
    status: str
    from_user: str
    to_user: str
    to_address: str
    amount_wei: str
    note: str
    created_at: str
    updated_at: str
    draft_tx: dict | None = None
    review_report: dict | None = None
    tx_hash: str | None = None
    error_message: str | None = None

class ReviewReport(BaseModel):
    intent_id: str
    digest: str
    verdict: str                    # "OK" | "WARN" | "BLOCK"
    reasons: list[str]
    summary: str
    gas_assessment: dict
    model_used: str = ""

class SignerResponse(BaseModel):
    tx_hash: str
    signed_at: str
```

---

## `requirements.txt`

```
fastapi>=0.100.0
uvicorn[standard]>=0.22.0
pydantic>=2.0.0
httpx>=0.25.0
python-dotenv>=1.0.0
web3>=6.0.0
eth-account>=0.8.0
```

Note: `transaction_builder` is imported directly as a local package (no separate install needed since it's in the same repo root).

---

## Rate Limiting

Copy the in-memory rate limiter middleware from `user_auth/app.py` verbatim. Set `RATE_LIMIT_MAX = 20` requests per minute per IP.

---

## Acceptance Criteria (how to verify the work is done)

The publisher service implementation is complete when all of the following pass:

### Manual smoke test

```bash
# 1. Start all services
uvicorn user_auth.app:app --port 8000 &
uvicorn signer_service.mock_server:app --port 8001 &
uvicorn reviewer_service.app:app --port 8003 &     # see reviewer spec
uvicorn publisher_service.app:app --port 8002 &

# 2. Submit an intent
DIGEST=$(python3 -m user_auth.generate_hmac ... )  # or use publisher's own HMAC
curl -X POST http://localhost:8002/intent \
  -H "X-API-Key: $PUBLISHER_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "intent_id": "smoke-test-001",
    "from_user": "userA",
    "to_user": "userB",
    "chain": "sepolia",
    "asset": "ETH",
    "amount_wei": "10000000000000000",
    "to_address": "0xd8da6bf26964af9d7eed9e03e53415d37aa96045",
    "note": "smoke test"
  }'
# Expected: 202 with status=pending

# 3. Poll until awaiting_approval
curl http://localhost:8002/intent/smoke-test-001 -H "X-API-Key: $PUBLISHER_API_KEY"
# Expected: status progresses through: pending → building → reviewing → awaiting_approval

# 4. Approve in Telegram
# (tap Approve button on the Telegram message)

# 5. Poll again
curl http://localhost:8002/intent/smoke-test-001 -H "X-API-Key: $PUBLISHER_API_KEY"
# Expected: status = broadcast or confirmed, tx_hash present
```

### Unit tests the agent must write (`tests/publisher_service/`)

The tests must cover:

1. **`test_api.py`** — FastAPI endpoint tests using `httpx.AsyncClient` and `TestClient`:
   - `POST /intent` returns 202 on valid input
   - `POST /intent` returns 401 with missing/wrong API key
   - `POST /intent` returns 409 on duplicate `intent_id`
   - `POST /intent` returns 422 on invalid address
   - `GET /intent/{id}` returns 404 for unknown id
   - `GET /intent/{id}` returns current status for known id
   - `GET /health` returns 200 with no auth

2. **`test_orchestrator.py`** — workflow logic tests with mocked clients:
   - Happy path: intent → `confirmed` status, `tx_hash` stored
   - Reviewer BLOCK → status becomes `blocked`, signing is never called
   - User rejection → status becomes `rejected`
   - Approval timeout → status becomes `expired`
   - PolicyError in builder → status becomes `failed` with error message
   - Consistency check: digest mismatch between draft and review report → `failed`
   - Consistency check: reviewer `WARN` does NOT block the flow (only `BLOCK` does)

3. **`test_clients.py`** — HTTP client tests using `respx` to mock httpx:
   - Reviewer 5xx → raises exception
   - Signer 4xx → raises exception (not silently swallowed)

### State machine invariants to assert in tests

```python
# These must always be true:
assert intent["status"] in (
    "pending", "building", "reviewing",
    "awaiting_approval", "signing", "broadcast", "confirmed",
    "rejected", "expired", "blocked", "failed"
)
# Once terminal, status must not change:
TERMINAL = {"confirmed", "rejected", "expired", "blocked", "failed"}
# store status before and after a no-op operation, assert unchanged
```

---

## Key Security Invariants (do not skip these)

1. **Digest consistency check is mandatory.** Before proceeding from review to approval, assert `review_report.digest == draft_tx.digest`. Log `SECURITY ALERT` and set status `failed` if they differ. This prevents a compromised reviewer from substituting a different transaction.

2. **Never re-use an `auth_request_id`.** Each intent gets a fresh UUID appended, preventing cross-intent approval replay.

3. **Do not proceed to signing if approval status is anything other than `"approved"`** — check the exact string, do not treat absence of rejection as approval.

4. **Log every state transition** with `intent_id`, `old_status`, `new_status`, and `timestamp` at INFO level.

---

## Notes for the Implementing Agent

- The `transaction_builder` package is already implemented and tested. Import it directly:
  `from transaction_builder import build_draft_tx, PolicyConfig, PolicyError, ProviderError, Web3Provider`

- The `user_auth` service is already running. Study `user_auth/security.py` for the HMAC signing pattern — you must replicate it in `clients.py` when calling `POST /auth/request`.

- The `reviewer_service` spec will be provided separately. For now, mock it: if `reviewer_service` is unreachable, default to `WARN` verdict (do not block, but do log).

- The `signer_service` mock at port 8001 (`signer_service/mock_server.py`) only has a callback endpoint — it does NOT yet have `POST /sign`. For testing the publisher, mock the signer response entirely:
  ```python
  # mock_signer_response
  {"tx_hash": "0x" + "aa" * 32, "signed_at": "2026-03-03T12:00:00+00:00"}
  ```

- Add `SEPOLIA_RPC_URL` to `.env`. For testing use a public RPC like `https://rpc.sepolia.org` or mock the `Web3Provider` in tests.

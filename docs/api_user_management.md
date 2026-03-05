# API User Management System

Per-agent API key management for the **publisher_service** with granular
permission controls: allowed tokens, allowed chains, per-transaction limits,
and daily spending caps — all configurable from the dashboard.

---

## Overview

Previously, publisher_service used a single shared `PUBLISHER_API_KEY` for all
callers. The API User Management system replaces this with **per-agent keys**,
each with its own permission set:

| Feature                | Description                                           |
| ---------------------- | ----------------------------------------------------- |
| **Allowed Assets**     | Which tokens the agent can submit intents for (ETH, USDC, etc.) |
| **Allowed Chains**     | Which chains the agent can operate on (sepolia, base, etc.)    |
| **Per-Tx Limit**       | Maximum amount (in wei) per single transaction        |
| **Daily Spending Cap** | Maximum total daily spend (resets at midnight UTC)    |
| **Rate Limit**         | Per-agent requests-per-minute (0 = server default)    |
| **Active/Inactive**    | Disable an agent instantly without deleting it        |

The original `PUBLISHER_API_KEY` from `.env` becomes the **admin key** — it
retains full access and is used to manage agents via the dashboard and API.

---

## Architecture

```
┌──────────────────────────────────────────────────────┐
│  Dashboard (api_users.html)                          │
│  ── uses admin key for all management operations     │
└───────────────┬──────────────────────────────────────┘
                │  CRUD via /api-users endpoints
                ▼
┌──────────────────────────────────────────────────────┐
│  publisher_service                                    │
│                                                       │
│  security.py   ← require_api_key()                    │
│    ├─ Admin key?   → full access, no restrictions     │
│    └─ Agent key?   → look up in DB, attach to request │
│                                                       │
│  app.py POST /intent                                  │
│    └─ check_agent_permission()                        │
│       ├─ Validate asset  ∈ allowed_assets             │
│       ├─ Validate chain  ∈ allowed_chains             │
│       ├─ Validate amount ≤ max_amount_wei             │
│       └─ Validate daily total ≤ daily_limit_wei       │
│                                                       │
│  api_users_db.py  (SQLite, same DB file)              │
│    ├─ api_users table                                 │
│    └─ api_user_daily_usage table                      │
└──────────────────────────────────────────────────────┘
```

### Two Auth Tiers

| Key Type     | How to get it              | Permissions                          |
| ------------ | -------------------------- | ------------------------------------ |
| **Admin**    | `PUBLISHER_API_KEY` in `.env` | Everything — CRUD agents, submit intents, view dashboard |
| **Agent**    | Created via `POST /api-users` | Only what the agent is permitted to do |

---

## Quick Start

### 1. Start the publisher service

```bash
python -m publisher_service.main
```

The API users database tables are created automatically on startup.

### 2. Open the management dashboard

Navigate to:
```
http://localhost:8002/dashboard/api-users
```

Or click the **🔑 API Users** button in the main dashboard header.

### 3. Create an agent

Fill in the form:
- **Agent Name**: A descriptive name (e.g., "OpenClaw Production")
- **Allowed Assets**: Type tokens and press Enter (e.g., `ETH`, `USDC`), or leave as `*` for all
- **Allowed Chains**: Type chains and press Enter (e.g., `sepolia`, `base`), or leave as `*` for all
- **Max per Tx**: Max wei per single transaction (0 = unlimited)
- **Daily Limit**: Max total wei per day (0 = unlimited)
- **Rate Limit**: Requests per minute (0 = server default)

Click **Create Agent & Generate Key**.

> ⚠️ **The API key is shown only once.** Copy and store it securely.

### 4. Use the agent key

The agent uses their key exactly like the old shared key:

```bash
curl -s -X POST http://localhost:8002/intent \
  -H "Content-Type: application/json" \
  -H "X-API-Key: csp_aBcDeFgHiJkLmNoPqRsTuVwXyZ123456789" \
  -d '{
    "intent_id": "pay-001",
    "from_user": "alice",
    "to_user": "bob",
    "amount_wei": "10000000000000000",
    "to_address": "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045",
    "chain": "sepolia",
    "asset": "ETH",
    "note": "lunch money"
  }'
```

If the agent tries to use a disallowed asset or chain, or exceeds a limit,
they get a **403 Forbidden** with a descriptive message.

---

## API Reference

All management endpoints require the **admin key** (`X-API-Key` header with
the value of `PUBLISHER_API_KEY`).

### Create Agent

```
POST /api-users
```

**Request:**
```json
{
  "name": "OpenClaw Agent",
  "allowed_assets": ["ETH", "USDC"],
  "allowed_chains": ["sepolia", "base"],
  "max_amount_wei": "500000000000000000",
  "daily_limit_wei": "2000000000000000000",
  "rate_limit": 30
}
```

**Response (201):**
```json
{
  "id": "a1b2c3d4e5f67890",
  "name": "OpenClaw Agent",
  "api_key": "csp_aBcDeFgHiJkLmNoPqRsTuVwXyZ123456789",
  "api_key_prefix": "csp_aBcDeFgH",
  "allowed_assets": ["ETH", "USDC"],
  "allowed_chains": ["sepolia", "base"],
  "max_amount_wei": "500000000000000000",
  "daily_limit_wei": "2000000000000000000",
  "rate_limit": 30,
  "is_active": true,
  "created_at": "2026-03-05T10:00:00+00:00",
  "updated_at": "2026-03-05T10:00:00+00:00"
}
```

> The `api_key` field is **only returned on creation** (and on regeneration).

### List Agents

```
GET /api-users
```

Returns an array of all agents (without plaintext keys).

### Get Agent

```
GET /api-users/{user_id}
```

### Update Agent

```
PUT /api-users/{user_id}
```

All fields are optional — only send what you want to change:

```json
{
  "allowed_assets": ["ETH"],
  "max_amount_wei": "100000000000000000",
  "is_active": false
}
```

### Delete (Deactivate) Agent

```
DELETE /api-users/{user_id}
```

Soft-deletes the agent (sets `is_active = false`). The agent's key immediately
stops working. Can be reactivated via `PUT` with `{"is_active": true}`.

### Regenerate API Key

```
POST /api-users/{user_id}/regenerate-key
```

Generates a new key. The **old key is permanently invalidated**.

**Response (200):** Same as create — includes the new `api_key` field.

### Get Usage

```
GET /api-users/{user_id}/usage
```

**Response:**
```json
{
  "id": "a1b2c3d4e5f67890",
  "name": "OpenClaw Agent",
  "today_total_wei": "150000000000000000",
  "today_request_count": 3,
  "daily_limit_wei": "2000000000000000000",
  "limit_remaining_wei": "1850000000000000000"
}
```

---

## Permission Matrix

| Permission       | Setting               | `"0"` / `["*"]` means | Enforcement point    |
| ---------------- | --------------------- | ---------------------- | -------------------- |
| Token allowlist  | `allowed_assets`      | All tokens allowed     | `POST /intent`       |
| Chain allowlist  | `allowed_chains`      | All chains allowed     | `POST /intent`       |
| Per-tx max       | `max_amount_wei`      | No per-tx limit        | `POST /intent`       |
| Daily cap        | `daily_limit_wei`     | No daily cap           | `POST /intent`       |
| Rate limit       | `rate_limit`          | Server default (60/min)| Middleware (planned)  |

### Error examples

**Disallowed asset:**
```json
{
  "detail": "Agent 'TestBot' is not permitted to transact BTC. Allowed: ['ETH', 'USDC']"
}
```

**Per-tx limit exceeded:**
```json
{
  "detail": "Amount 1000000000000000000 exceeds per-transaction limit of 500000000000000000 wei for agent 'TestBot'."
}
```

**Daily limit exceeded:**
```json
{
  "detail": "Daily limit exceeded for agent 'TestBot'. Limit: 2000000000000000000 wei, used today: 1800000000000000000 wei, remaining: 200000000000000000 wei."
}
```

---

## Security

- **API keys** are stored as **SHA-256 hashes** — the plaintext is never
  persisted and is shown only once on creation (or regeneration).
- Key prefix (`csp_aBcDeFgH…`) is stored for display purposes only.
- **Admin key** (`PUBLISHER_API_KEY`) is required for all management
  operations. Agent keys cannot create/list/modify other agents.
- **Soft delete**: Deactivated agents can be reactivated. For permanent
  deletion, remove the row manually from SQLite.
- **Daily usage** resets automatically at midnight UTC. Historical usage data
  is retained in the `api_user_daily_usage` table.

---

## Database Schema

Two tables are added to the publisher_service SQLite database:

```sql
CREATE TABLE api_users (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    api_key_hash    TEXT NOT NULL UNIQUE,
    api_key_prefix  TEXT NOT NULL,
    allowed_assets  TEXT NOT NULL DEFAULT '["*"]',   -- JSON array
    allowed_chains  TEXT NOT NULL DEFAULT '["*"]',   -- JSON array
    max_amount_wei  TEXT NOT NULL DEFAULT '0',
    daily_limit_wei TEXT NOT NULL DEFAULT '0',
    rate_limit      INTEGER NOT NULL DEFAULT 0,
    is_active       INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE TABLE api_user_daily_usage (
    user_id         TEXT NOT NULL,
    date_utc        TEXT NOT NULL,          -- "YYYY-MM-DD"
    total_wei       TEXT NOT NULL DEFAULT '0',
    request_count   INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, date_utc),
    FOREIGN KEY (user_id) REFERENCES api_users(id)
);
```

---

## Dashboard

The management UI is at `/dashboard/api-users` and provides:

- **Stats bar**: Total agents, active count, inactive count
- **Create form**: Full form with chip-based multi-select for assets/chains
- **Agent table**: All agents with status, permissions, key prefix, and actions
- **Inline actions**: Edit, regenerate key, deactivate/reactivate per agent
- **Key modal**: Shows the generated key with copy button and warning
- **Edit modal**: Quick-edit all permissions for any agent

The dashboard uses the same visual theme as the main transaction dashboard.

---

## Backward Compatibility

- The **admin key** (`PUBLISHER_API_KEY`) continues to work exactly as before
  for all endpoints, with zero restrictions.
- Existing integrations using the shared key will not break.
- New agents can be created at any time; the system is purely additive.

---

## Running Tests

```bash
# API user management tests only
pytest tests/publisher_service/test_api_users.py -v

# All publisher_service tests (includes existing + new)
pytest tests/publisher_service/ -v
```

The test suite covers:
- Full CRUD (create, list, get, update, delete)
- API key regeneration and old-key invalidation
- Asset permission enforcement (wildcard, allowed, disallowed)
- Chain permission enforcement
- Per-transaction amount limits
- Daily spending cap with accumulation
- Inactive agent rejection
- Admin key bypass (no restrictions)
- Agent keys blocked from management endpoints
- Usage tracking and reporting

---

## Files Added / Modified

| File | Type | Description |
|------|------|-------------|
| `publisher_service/api_users_db.py` | **New** | SQLite CRUD + usage tracking for API users |
| `publisher_service/api_user_models.py` | **New** | Pydantic request/response models |
| `publisher_service/security.py` | **Modified** | Dual-tier auth (admin + agent), permission checks |
| `publisher_service/app.py` | **Modified** | API user CRUD endpoints, permission enforcement on `/intent` |
| `dashboard/api_users.html` | **New** | Management dashboard page |
| `dashboard/index.html` | **Modified** | Added nav link to API Users page |
| `tests/publisher_service/test_api_users.py` | **New** | 28 tests covering the full feature |
| `tests/publisher_service/conftest.py` | **Modified** | Patched api_users_db for test isolation |
| `docs/api_user_management.md` | **New** | This documentation file |

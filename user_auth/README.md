# User Auth Service

Telegram-based two-factor authentication gateway for **ClawSafe Pay**.

The `signer_service` sends an authentication request here; the service forwards it to a Telegram user via an inline-keyboard message. The user taps **Approve** or **Reject** on Telegram, and the result is stored locally and sent back to `signer_service` via its callback endpoint.

---

## Architecture Overview

```
signer_service                  user_auth                       Telegram
     │                              │                              │
     │  POST /auth/request          │                              │
     │ ──────────────────────────►  │  sendMessage (inline kbd)    │
     │                              │ ────────────────────────────► │
     │                              │                              │
     │                              │  webhook callback_query      │
     │                              │ ◄──────────────────────────── │
     │  POST /auth/callback         │                              │
     │ ◄──────────────────────────  │  editMessageText             │
     │                              │ ────────────────────────────► │
```

---

## Prerequisites

| Tool | Version |
|------|---------|
| Python | 3.11+ |
| pip | latest |

A **Telegram Bot** token and a **chat ID** (your own or a group's) are required. See [Telegram Bot Setup](#telegram-bot-setup) below.

---

## Quick Start

### 1. Install dependencies

```bash
cd clawsafe_pay
pip install -r user_auth/requirements.txt
```

### 2. Configure environment variables

Copy the template below into the project root `.env` file:

```dotenv
# Telegram
TELEGRAM_BOT_TOKEN=123456:ABC-DEF...        # from @BotFather
TELEGRAM_CHAT_ID=987654321                   # your Telegram user/group ID

# Signer service callback (mock runs on port 8001)
SIGNER_SERVICE_CALLBACK_URL=http://localhost:8001/auth/callback

# HMAC shared secret – must match what signer_service uses
# Generation Script: openssl rand -base64 32
HMAC_SECRET=my-super-secret-key

# Optional overrides
# AUTH_SERVICE_PORT=8000
# AUTH_REQUEST_TTL_SECONDS=300
```

### 3. Initialise the database

```bash
python -m user_auth.database
```

This creates `user_auth/auth_requests.db` (SQLite).

### 4. Start the services

In **two terminals**:

```bash
# Terminal 1 – user_auth service (port 8000)
uvicorn user_auth.app:app --reload --port 8000

# Terminal 2 – mock signer_service (port 8001)
uvicorn signer_service.mock_server:app --reload --port 8001
```

### 5. Set up the Telegram webhook

Point your bot's webhook at your publicly accessible URL (use [ngrok](https://ngrok.com) for local development):

```bash
ngrok http 8000
```

Then register the webhook with Telegram:

```bash
curl -X POST "https://api.telegram.org/bot<YOUR_TOKEN>/setWebhook" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://<NGROK_SUBDOMAIN>.ngrok-free.app/telegram/webhook"}'
```

---

## API Reference

### `POST /auth/request`

Create a new authentication request.

**Request body** (`application/json`):

| Field | Type | Description |
|-------|------|-------------|
| `request_id` | string | Unique UUID for this transaction |
| `user_id` | string | Identifier of the user to authenticate |
| `action` | string | Human-readable description of the action |
| `hmac_digest` | string | HMAC-SHA256 over `request_id:user_id:action` |

**Response** `200`:

```json
{
  "request_id": "abc-123",
  "status": "pending",
  "message": "Auth request sent to user via Telegram"
}
```

**Errors**:

| Code | Reason |
|------|--------|
| 403 | Invalid HMAC signature |
| 409 | Duplicate `request_id` (replay attempt) |

### `GET /auth/{request_id}`

Poll the status of an existing request.

**Response** `200`:

```json
{
  "request_id": "abc-123",
  "user_id": "user42",
  "action": "Sign contract #7",
  "status": "approved",
  "created_at": "2026-03-03T12:00:00+00:00",
  "resolved_at": "2026-03-03T12:01:30+00:00"
}
```

### `POST /telegram/webhook`

Telegram sends inline-keyboard callback updates here. Not called manually.

### `GET /health`

Returns `{"status": "ok"}`.

---

## Testing with cURL

### Generate a valid HMAC digest

```bash
python -m user_auth.generate_hmac "abc-123" "user42" "Sign contract #7"
```

### Submit an auth request

```bash
curl -X POST http://localhost:8000/auth/request \
  -H "Content-Type: application/json" \
  -d '{
    "request_id": "abc-123",
    "user_id": "user42",
    "action": "Sign contract #7",
    "hmac_digest": "<paste digest from above>"
  }'
```

### Check the status

```bash
curl http://localhost:8000/auth/status/abc-123
```

---

## Security Features

| Feature | Description |
|---------|-------------|
| **HMAC-SHA256 request signing** | Every request must include a valid HMAC digest computed with a shared secret. Prevents unauthorised submissions. |
| **Unique request ID (anti-replay)** | Each `request_id` is stored; duplicates are rejected with HTTP 409. Old authorisations cannot be reused. |
| **Automatic expiry (TTL)** | Pending requests expire after `AUTH_REQUEST_TTL_SECONDS` (default 5 min). A background task marks them as `expired` and notifies `signer_service`. |
| **Rate limiting** | In-memory per-IP rate limiter (30 req/min by default) protects against abuse. |
| **Telegram message lockdown** | After a decision, the inline keyboard is removed from the Telegram message so buttons cannot be tapped again. |
| **Constant-time HMAC comparison** | Uses `hmac.compare_digest` to prevent timing side-channel attacks. |

---

## Database Schema

Single table `auth_requests` in SQLite:

| Column | Type | Description |
|--------|------|-------------|
| `request_id` | TEXT PK | UUID supplied by signer_service |
| `user_id` | TEXT | User identifier |
| `action` | TEXT | Description of the action |
| `status` | TEXT | `pending` / `approved` / `rejected` / `expired` |
| `hmac_digest` | TEXT | HMAC-SHA256 digest |
| `created_at` | TEXT | ISO-8601 UTC |
| `resolved_at` | TEXT | ISO-8601 UTC (null while pending) |
| `telegram_message_id` | INTEGER | Telegram message ID |
| `callback_sent` | INTEGER | `1` once signer_service was notified |

---

## Telegram Bot Setup

1. Open Telegram and search for **@BotFather**.
2. Send `/newbot` and follow the prompts to create a bot.
3. Copy the **bot token** into `TELEGRAM_BOT_TOKEN`.
4. To find your **chat ID**, message the bot, then visit:
   ```
   https://api.telegram.org/bot<TOKEN>/getUpdates
   ```
   Look for `"chat": {"id": 123456789}`.
5. Put that ID in `TELEGRAM_CHAT_ID`.

---

## Project Structure

```
user_auth/
├── __init__.py
├── app.py              # FastAPI application & routes
├── config.py           # Environment-based configuration
├── database.py         # SQLite DB setup & CRUD helpers
├── generate_hmac.py    # CLI tool to create test HMAC digests
├── main.py             # uvicorn entry-point
├── models.py           # Pydantic request/response models
├── requirements.txt    # Python dependencies
├── security.py         # HMAC signing & verification
├── signer_callback.py  # HTTP client for signer_service callback
└── telegram_bot.py     # Telegram API integration

signer_service/
├── __init__.py
└── mock_server.py      # Mock callback endpoint for testing
```

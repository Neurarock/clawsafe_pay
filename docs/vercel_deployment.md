# Vercel Deployment Guide for ClawSafe Pay (Telegram Webhook)

## Overview

The user_auth Telegram webhook handler is **stateless** by design — it receives
a callback, updates the DB, and returns.  This makes it ideal for serverless
deployment on Vercel (or any similar platform).

## Architecture

```
Telegram ──▶ Vercel Edge/Serverless Function ──▶ DB (Turso/PlanetScale/Neon)
               POST /api/telegram/webhook           ▲
                                                     │
User's browser ──▶ Vercel ──▶ DB ──────────────────────┘
```

## Setup Steps

### 1. Environment Variables (Vercel Dashboard)

Set these in your Vercel project settings → Environment Variables:

| Variable | Description | Example |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Bot token from @BotFather | `8605630801:AAF...` |
| `TELEGRAM_WEBHOOK_URL` | Your Vercel deployment URL | `https://clawsafe.vercel.app/api/telegram/webhook` |
| `TELEGRAM_WEBHOOK_SECRET` | Random secret for webhook auth | `your-random-secret-here` |
| `TELEGRAM_CHAT_ID` | Default fallback chat ID | `-5239918904` |
| `DATABASE_URL` | External DB connection string | `libsql://...turso.io` |
| `HMAC_SECRET` | Shared secret for service auth | `production-secret` |

### 2. Register Webhook (one-time, or post-deploy hook)

```bash
# From project root:
python scripts/setup_telegram_webhook.py \
  --url https://clawsafe.vercel.app/api/telegram/webhook
```

Or use the admin API:
```bash
curl -X POST https://clawsafe.vercel.app/admin/webhook/register \
  -H "Content-Type: application/json" \
  -d '{"url": "https://clawsafe.vercel.app/api/telegram/webhook"}'
```

### 3. Vercel API Route

Create `api/telegram/webhook.py`:

```python
# api/telegram/webhook.py  (Vercel serverless function)
from fastapi import FastAPI, Request, HTTPException
from user_auth.telegram_handler import process_callback
from user_auth.config import TELEGRAM_WEBHOOK_SECRET

app = FastAPI()

@app.post("/api/telegram/webhook")
async def telegram_webhook(request: Request):
    # Verify secret
    if TELEGRAM_WEBHOOK_SECRET:
        token = request.headers.get("x-telegram-bot-api-secret-token", "")
        if token != TELEGRAM_WEBHOOK_SECRET:
            raise HTTPException(status_code=403)

    body = await request.json()
    cq = body.get("callback_query")
    if cq:
        await process_callback(cq)
    return {"ok": True}
```

### 4. Database Migration

Replace SQLite with an external database for serverless:

- **Turso** (libSQL) — drop-in SQLite-compatible, great for migration
- **PlanetScale** — MySQL-compatible
- **Neon** — PostgreSQL serverless

The existing `database.py` modules use raw SQL that's
SQLite-compatible → Turso migration is nearly zero-effort.

## Key Design Decisions

1. **Webhook handler is stateless** — no background tasks, no polling loops
2. **Secret token verification** — prevents spoofed webhook calls
3. **`process_callback()` is self-contained** — reads from DB, updates DB, calls Telegram API
4. **No long-polling in serverless** — webhooks are the only option
5. **Admin endpoints** for webhook management without redeployment

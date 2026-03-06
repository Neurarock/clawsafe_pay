# ClawSafe Pay — Vercel Deployment Instructions

> Complete step-by-step guide to deploy the ClawSafe Pay multi-service platform on Vercel.

---

## Table of Contents

- [ClawSafe Pay — Vercel Deployment Instructions](#clawsafe-pay--vercel-deployment-instructions)
  - [Table of Contents](#table-of-contents)
  - [1. Architecture Overview](#1-architecture-overview)
    - [Local / Docker (current)](#local--docker-current)
    - [Vercel (target)](#vercel-target)
  - [2. Prerequisites](#2-prerequisites)
  - [3. Deployment Strategy](#3-deployment-strategy)
  - [Step 1 — Set Up a Hosted Database](#step-1--set-up-a-hosted-database)
    - [Option A: Turso (recommended — SQLite-compatible)](#option-a-turso-recommended--sqlite-compatible)
    - [Option B: Neon (PostgreSQL)](#option-b-neon-postgresql)
  - [Step 2 — Create the Vercel Project](#step-2--create-the-vercel-project)
  - [Step 3 — Add `vercel.json`](#step-3--add-verceljson)
  - [Step 4 — Add `requirements.txt` (Root)](#step-4--add-requirementstxt-root)
  - [Step 5 — Create the Unified API Entry Point](#step-5--create-the-unified-api-entry-point)
  - [Step 6 — Configure Environment Variables](#step-6--configure-environment-variables)
    - [Required](#required)
    - [Wallets (private keys — mark as **Secret**)](#wallets-private-keys--mark-as-secret)
    - [Service URLs (internal to Vercel — same domain)](#service-urls-internal-to-vercel--same-domain)
    - [Database (Turso example)](#database-turso-example)
    - [Policy](#policy)
  - [Step 7 — Migrate SQLite → Hosted DB](#step-7--migrate-sqlite--hosted-db)
    - [Install the Turso Python SDK](#install-the-turso-python-sdk)
    - [Adapt each `database.py`](#adapt-each-databasepy)
    - [Seed the hosted databases](#seed-the-hosted-databases)
  - [Step 8 — Register the Telegram Webhook](#step-8--register-the-telegram-webhook)
    - [Option A: CLI script (recommended)](#option-a-cli-script-recommended)
    - [Option B: curl](#option-b-curl)
    - [Option C: Admin endpoint (after deploy)](#option-c-admin-endpoint-after-deploy)
    - [Verify webhook status](#verify-webhook-status)
  - [Step 9 — Deploy](#step-9--deploy)
    - [First deploy](#first-deploy)
    - [Subsequent deploys (via Git push)](#subsequent-deploys-via-git-push)
    - [Manual redeploy](#manual-redeploy)
  - [Step 10 — Verify](#step-10--verify)
  - [Troubleshooting](#troubleshooting)
    - ["Module not found" errors](#module-not-found-errors)
    - [Telegram webhook not receiving callbacks](#telegram-webhook-not-receiving-callbacks)
    - [Serverless function timeout](#serverless-function-timeout)
    - [Database connection issues](#database-connection-issues)
    - [Cold start latency](#cold-start-latency)
  - [Production Checklist](#production-checklist)
  - [File Structure After Changes](#file-structure-after-changes)
  - [Quick-Start Summary](#quick-start-summary)

---

## 1. Architecture Overview

### Local / Docker (current)

```
┌─────────┐  ┌────────┐  ┌───────────┐  ┌──────────┐  ┌──────────┐
│ frontend │→│publisher│→│  reviewer  │  │  signer  │→│ user_auth│
│  :8008   │ │  :8002  │ │   :8003   │  │  :8001   │ │  :8000   │
└─────────┘  └────────┘  └───────────┘  └──────────┘  └──────────┘
5 Docker services, SQLite files, Telegram long-polling
```

### Vercel (target)

```
┌──────────────────────────────────────────────────────────────────┐
│                     Vercel Project                               │
│                                                                  │
│  /api/publisher/*   → publisher_service   (serverless function) │
│  /api/signer/*      → signer_service      (serverless function) │
│  /api/user-auth/*   → user_auth           (serverless function) │
│  /api/reviewer/*    → reviewer_service    (serverless function) │
│  /*                 → frontend            (serverless function) │
│                                                                  │
│  DB: Turso (libSQL) / Neon (Postgres) / PlanetScale (MySQL)    │
│  Telegram: Webhook mode (no long-polling)                        │
└──────────────────────────────────────────────────────────────────┘
```

**Key change:** All 5 services run as serverless functions behind a single Vercel domain, communicating via internal HTTP calls (same domain, zero latency). SQLite is replaced by a hosted DB.

---

## 2. Prerequisites

- **Vercel account** — [vercel.com/signup](https://vercel.com/signup)
- **Vercel CLI** — `npm i -g vercel`
- **Python 3.11+** locally (for testing)
- **Git repo** — this project pushed to GitHub/GitLab
- **Telegram Bot** — already created via @BotFather (token: `TELEGRAM_BOT_TOKEN`)
- **Hosted database** — Turso (recommended, SQLite-compatible), Neon, or PlanetScale

---

## 3. Deployment Strategy

Vercel supports Python serverless functions via FastAPI. We expose each backend
service as a sub-path under `/api/`, and the frontend as the catch-all route.

| Local Service | Port | Vercel Route |
|---|---|---|
| `frontend` | 8008 | `/*` (catch-all) |
| `publisher_service` | 8002 | `/api/publisher/{path}` |
| `signer_service` | 8001 | `/api/signer/{path}` |
| `user_auth` | 8000 | `/api/user-auth/{path}` |
| `reviewer_service` | 8003 | `/api/reviewer/{path}` |

---

## Step 1 — Set Up a Hosted Database

SQLite does not work on Vercel (no persistent filesystem). Choose one:

### Option A: Turso (recommended — SQLite-compatible)

```bash
# Install Turso CLI
brew install tursodatabase/tap/turso    # macOS
# or: curl -sSfL https://get.tur.so/install.sh | bash

# Login
turso auth signup

# Create databases (one per service)
turso db create clawsafe-publisher
turso db create clawsafe-signer
turso db create clawsafe-userauth

# Get connection URLs
turso db show clawsafe-publisher --url    # → libsql://clawsafe-publisher-<you>.turso.io
turso db show clawsafe-signer --url
turso db show clawsafe-userauth --url

# Create auth tokens
turso db tokens create clawsafe-publisher
turso db tokens create clawsafe-signer
turso db tokens create clawsafe-userauth
```

### Option B: Neon (PostgreSQL)

```bash
# Go to https://neon.tech and create a project
# Copy the connection string:  postgres://user:pass@ep-xxx.us-east-2.aws.neon.tech/dbname
```

> **Note:** If using Neon/PlanetScale, you'll also need to adapt the raw SQL in each `database.py` file to use PostgreSQL/MySQL syntax instead of SQLite. Turso requires no SQL changes.

---

## Step 2 — Create the Vercel Project

```bash
cd /path/to/clawsafe_pay

# Link to Vercel (creates .vercel/ directory)
vercel link

# Or create a new project
vercel
```

Select:
- **Framework:** Other
- **Root directory:** `.` (project root)
- **Build command:** (leave empty or use the one below)
- **Output directory:** (leave empty)

---

## Step 3 — Add `vercel.json`

Create this file in the project root:

```json
{
  "$schema": "https://openapi.vercel.sh/vercel.json",
  "version": 2,
  "buildCommand": "pip install -r requirements.txt",
  "builds": [
    {
      "src": "api/index.py",
      "use": "@vercel/python",
      "config": {
        "maxLambdaSize": "50mb"
      }
    }
  ],
  "rewrites": [
    {
      "source": "/api/publisher/(.*)",
      "destination": "/api/index.py"
    },
    {
      "source": "/api/signer/(.*)",
      "destination": "/api/index.py"
    },
    {
      "source": "/api/user-auth/(.*)",
      "destination": "/api/index.py"
    },
    {
      "source": "/api/reviewer/(.*)",
      "destination": "/api/index.py"
    },
    {
      "source": "/telegram/webhook",
      "destination": "/api/index.py"
    },
    {
      "source": "/health",
      "destination": "/api/index.py"
    },
    {
      "source": "/((?!api|_next|static|favicon).*)",
      "destination": "/api/index.py"
    }
  ],
  "headers": [
    {
      "source": "/static/(.*)",
      "headers": [
        { "key": "Cache-Control", "value": "public, max-age=31536000, immutable" }
      ]
    }
  ],
  "env": {
    "PYTHONPATH": "/var/task/backend:/var/task"
  }
}
```

---

## Step 4 — Add `requirements.txt` (Root)

Create a **root-level** `requirements.txt` that merges all service dependencies:

```txt
# ── Root requirements.txt for Vercel ──────────────────────────
# Combines all service dependencies into a single install.

# Core framework
fastapi>=0.110.0
uvicorn[standard]>=0.29.0
pydantic>=2.0.0
httpx>=0.27.0
python-dotenv>=1.0.0

# Blockchain (publisher + signer)
web3>=6.0.0
eth-account>=0.8.0

# Frontend
aiofiles>=23.0.0

# Database — uncomment ONE of these based on your DB choice:
# libsql-experimental>=0.0.40    # for Turso (libSQL)
# asyncpg>=0.29.0                # for Neon (PostgreSQL)
# aiomysql>=0.2.0                # for PlanetScale (MySQL)
```

---

## Step 5 — Create the Unified API Entry Point

Create `api/index.py` — this is the single serverless function that routes to all backend services:

```python
"""
Vercel serverless entry point.

Maps all service routes to their respective FastAPI apps behind a
single ASGI handler. This file is the target of all rewrites in
vercel.json.
"""
from __future__ import annotations

import os
import sys

# ── Ensure backend packages are importable ──────────────────────────
# Vercel extracts the project to /var/task.  PYTHONPATH is set in
# vercel.json but we also do it here defensively.
_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_backend = os.path.join(_root, "backend")
for p in (_root, _backend):
    if p not in sys.path:
        sys.path.insert(0, p)

# ── Unified FastAPI app ─────────────────────────────────────────────
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="ClawSafe Pay", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Mount sub-applications ──────────────────────────────────────────
# Each service's FastAPI app is mounted at its prefix.

from publisher_service.app import app as publisher_app
from signer_service.app import app as signer_app
from user_auth.app import app as user_auth_app
from reviewer_service.app import app as reviewer_app
from frontend.app import app as frontend_app

app.mount("/api/publisher", publisher_app)
app.mount("/api/signer", signer_app)
app.mount("/api/user-auth", user_auth_app)
app.mount("/api/reviewer", reviewer_app)

# Telegram webhook at top level for a clean URL
from user_auth.models import TelegramUpdate
from user_auth.config import TELEGRAM_WEBHOOK_SECRET
from user_auth import telegram_handler

@app.post("/telegram/webhook")
async def telegram_webhook(update: TelegramUpdate, request: Request):
    if TELEGRAM_WEBHOOK_SECRET:
        token = request.headers.get("x-telegram-bot-api-secret-token", "")
        if token != TELEGRAM_WEBHOOK_SECRET:
            return JSONResponse(status_code=403, content={"detail": "Invalid secret"})
    cq = update.callback_query
    if cq:
        import asyncio
        asyncio.create_task(telegram_handler.process_callback(cq))
    return {"ok": True}

@app.get("/health")
async def health():
    return {"status": "ok", "services": ["publisher", "signer", "user_auth", "reviewer", "frontend"]}

# Frontend catch-all (must be last)
app.mount("/", frontend_app)
```

> **Important:** This single `api/index.py` file is what Vercel runs as a serverless function. All 5 services are imported and mounted as sub-apps.

---

## Step 6 — Configure Environment Variables

In the Vercel dashboard → Project Settings → Environment Variables, set **all** of these:

### Required

| Variable | Value | Notes |
|---|---|---|
| `PYTHONPATH` | `/var/task/backend:/var/task` | So imports work |
| `TELEGRAM_BOT_TOKEN` | `8605630801:AAFG9...` | From @BotFather |
| `TELEGRAM_CHAT_ID` | `-5239918904` | Default fallback group |
| `TELEGRAM_WEBHOOK_URL` | `https://<your-app>.vercel.app/telegram/webhook` | Full public URL |
| `TELEGRAM_WEBHOOK_SECRET` | `<random-32-char-string>` | Generate with `openssl rand -base64 32` |
| `HMAC_SECRET` | `ckDhTstYUaZok/gdcVLp7+jLAY/q3E9dPKQUZWIAmAI=` | Must match signer ↔ user_auth |
| `PUBLISHER_API_KEY` | `<strong-admin-key>` | Admin key for publisher |
| `DEFAULT_PUBLISHER_API` | `<seeded-dashboard-key>` | Dashboard agent key |
| `ZAI_API_KEY` | `85139484f4e44...` | Z.AI GLM-5 for tx reviews |
| `FLOCK_API_KEY` | `sk-kpW5e86reYZsZPS8NQbXsA` | Flock injection filter |
| `SEPOLIA_RPC_URL` | `https://ethereum-sepolia-rpc.publicnode.com` | Or your Infura/Alchemy URL |

### Wallets (private keys — mark as **Secret**)

| Variable | Value |
|---|---|
| `WALLET_ADDR_1` | `0xd77E4F8142a0C48A62601cD5Be99f591D2D515da` |
| `WALLET_PRIV_KEY_1` | `0xb0c8d34bd9d081d7c3d54aea0bdde439cc82b2b5daf77ecd1fd96152b8fca23e` |
| `WALLET_ADDR_2` | `0x52492C6B4635E6b87f2043A6Ac274Be458060b48` |
| `WALLET_PRIV_KEY_2` | `0x4fe54e621e58bc245669aa7c0635f4bc9e503145823d9b50eafc32d0d6410389` |
| `SIGNER_FROM_ADDRESS` | `0xd77E4F8142a0C48A62601cD5Be99f591D2D515da` |

### Service URLs (internal to Vercel — same domain)

| Variable | Value | Notes |
|---|---|---|
| `SIGNER_SERVICE_URL` | `https://<your-app>.vercel.app/api/signer` | Publisher → Signer |
| `REVIEWER_SERVICE_URL` | `https://<your-app>.vercel.app/api/reviewer` | Publisher → Reviewer |
| `USER_AUTH_URL` | `https://<your-app>.vercel.app/api/user-auth` | Signer → User Auth |
| `SIGNER_SERVICE_CALLBACK_URL` | `https://<your-app>.vercel.app/api/signer/auth/callback` | User Auth → Signer |
| `PUBLISHER_API_URL` | `https://<your-app>.vercel.app/api/publisher` | Frontend → Publisher |
| `PUBLISHER_BROWSER_URL` | `/api/publisher` | Browser-side relative URL |

### Database (Turso example)

| Variable | Value |
|---|---|
| `DATABASE_URL_PUBLISHER` | `libsql://clawsafe-publisher-<you>.turso.io` |
| `DATABASE_URL_SIGNER` | `libsql://clawsafe-signer-<you>.turso.io` |
| `DATABASE_URL_USERAUTH` | `libsql://clawsafe-userauth-<you>.turso.io` |
| `TURSO_AUTH_TOKEN_PUBLISHER` | `<token>` |
| `TURSO_AUTH_TOKEN_SIGNER` | `<token>` |
| `TURSO_AUTH_TOKEN_USERAUTH` | `<token>` |

### Policy

| Variable | Value |
|---|---|
| `POLICY_RECIPIENT_ALLOWLIST` | `*` |
| `POLICY_MAX_AMOUNT_WEI` | `1000000000000000000` |

---

## Step 7 — Migrate SQLite → Hosted DB

Each service has a `database.py` that uses `sqlite3` directly. For Turso (libSQL), the migration is minimal:

### Install the Turso Python SDK

Add to root `requirements.txt`:
```
libsql-experimental>=0.0.40
```

### Adapt each `database.py`

Replace the SQLite connection pattern:

**Before (SQLite):**
```python
import sqlite3
def _connect():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn
```

**After (Turso / libSQL):**
```python
import libsql_experimental as libsql
import os

def _connect():
    url = os.getenv("DATABASE_URL_PUBLISHER")  # adjust per service
    token = os.getenv("TURSO_AUTH_TOKEN_PUBLISHER")
    conn = libsql.connect(database=url, auth_token=token)
    conn.row_factory = libsql.Row  # same as sqlite3.Row
    return conn
```

The rest of the SQL stays identical — Turso is wire-compatible with SQLite.

### Seed the hosted databases

```bash
# Apply seed data to each Turso database
turso db shell clawsafe-publisher < seed/publisher.sql
turso db shell clawsafe-signer < seed/signer.sql
turso db shell clawsafe-userauth < seed/user_auth.sql
```

---

## Step 8 — Register the Telegram Webhook

After the first successful deploy, register the webhook URL with Telegram:

### Option A: CLI script (recommended)

```bash
# From project root, with .venv activated:
source .venv/bin/activate

export TELEGRAM_BOT_TOKEN="8605630801:AAFG9jUwrDRqr_QrsCMgmES497DJ4FJLCck"
export TELEGRAM_WEBHOOK_SECRET="<your-secret>"

python scripts/setup_telegram_webhook.py \
  --url "https://<your-app>.vercel.app/telegram/webhook" \
  --secret "$TELEGRAM_WEBHOOK_SECRET"
```

### Option B: curl

```bash
# Direct Telegram API call
curl -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/setWebhook" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://<your-app>.vercel.app/telegram/webhook",
    "allowed_updates": ["callback_query"],
    "secret_token": "<your-secret>"
  }'
```

### Option C: Admin endpoint (after deploy)

```bash
curl -X POST "https://<your-app>.vercel.app/api/user-auth/admin/webhook/register" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://<your-app>.vercel.app/telegram/webhook"}'
```

### Verify webhook status

```bash
python scripts/setup_telegram_webhook.py --info
# or
curl "https://<your-app>.vercel.app/api/user-auth/admin/webhook/info"
```

---

## Step 9 — Deploy

### First deploy

```bash
# From project root
vercel --prod
```

### Subsequent deploys (via Git push)

```bash
git add -A
git commit -m "deploy to vercel"
git push    # Vercel auto-deploys from connected Git repo
```

### Manual redeploy

```bash
vercel --prod --force
```

---

## Step 10 — Verify

After deployment, run through this checklist:

```bash
YOUR_APP="https://<your-app>.vercel.app"

# 1. Health check
curl "$YOUR_APP/health"
# Expected: {"status":"ok","services":[...]}

# 2. Publisher health
curl "$YOUR_APP/api/publisher/health"
# Expected: {"status":"ok"}

# 3. Signer health
curl "$YOUR_APP/api/signer/health"

# 4. User Auth health
curl "$YOUR_APP/api/user-auth/health"

# 5. Reviewer health
curl "$YOUR_APP/api/reviewer/health"

# 6. Frontend loads
curl -s "$YOUR_APP/" | head -5
# Expected: HTML content

# 7. Telegram webhook info
curl "$YOUR_APP/api/user-auth/admin/webhook/info"
# Expected: {"url":"https://...","mode":"webhook","pending_update_count":0}

# 8. Submit a test intent (replace with your agent key)
curl -X POST "$YOUR_APP/api/publisher/intent" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: <your-agent-api-key>" \
  -d '{
    "intent_id": "vercel-test-001",
    "from_user": "alice",
    "to_user": "bob",
    "amount_wei": "100000000000000",
    "to_address": "0x52492C6B4635E6b87f2043A6Ac274Be458060b48",
    "note": "Vercel deployment test",
    "chain": "sepolia",
    "asset": "ETH"
  }'
# Expected: {"intent_id":"vercel-test-001","status":"pending",...}
# Then check Telegram for the auth prompt!
```

---

## Troubleshooting

### "Module not found" errors

- Ensure `PYTHONPATH` is set to `/var/task/backend:/var/task` in Vercel env vars.
- Ensure `api/index.py` has the `sys.path` setup at the top.

### Telegram webhook not receiving callbacks

```bash
# Check webhook status
python scripts/setup_telegram_webhook.py --info

# Common issues:
# - URL not HTTPS (Telegram requires HTTPS)
# - Secret token mismatch
# - Bot token invalid
# - Webhook URL unreachable (deploy not finished)

# Fix: re-register after deploy completes
python scripts/setup_telegram_webhook.py \
  --url "https://<your-app>.vercel.app/telegram/webhook"
```

### Serverless function timeout

Vercel has a **10-second timeout** on the Hobby plan (60s on Pro). The signer
workflow polls user_auth for Telegram approval, which can take minutes.

**Solutions:**
1. **Upgrade to Vercel Pro** (60s function duration) — still not enough for the full poll loop.
2. **Use Vercel Cron + async pattern:**
   - `/api/signer/sign` returns immediately after storing the request
   - A Vercel Cron job polls for pending auths every 10 seconds
   - Or use a webhook callback architecture (user_auth already calls signer's `/auth/callback`)
3. **Keep signer as an external service** — run signer on Railway/Fly.io/Render where long-running processes are supported, and only deploy the stateless services (frontend, publisher, reviewer, user_auth webhook handler) on Vercel.

### Database connection issues

- Verify database URLs and tokens are correct in Vercel env vars.
- Check that the Turso/Neon region matches your Vercel deployment region (use `iad1` / US East for both).
- Run `turso db shell <name>` to verify tables exist.

### Cold start latency

Vercel serverless functions have cold starts (~1-3s for Python). To mitigate:
- Keep the function bundle small (avoid unnecessary dependencies)
- Vercel Pro has "Always Warm" options
- The `web3` package is large — consider lazy-importing it only in code paths that need it

---

## Production Checklist

- [ ] **Replace all default secrets** — `PUBLISHER_API_KEY`, `HMAC_SECRET`, `TELEGRAM_WEBHOOK_SECRET`
- [ ] **Use production wallet keys** — never commit private keys to Git; use Vercel Secrets
- [ ] **Set up a production RPC** — use Infura/Alchemy instead of public endpoints for reliability
- [ ] **Enable Vercel Pro** if you need >10s function duration
- [ ] **Set up monitoring** — Vercel Analytics + Sentry for error tracking
- [ ] **Custom domain** — `vercel domains add yourdomain.com`
- [ ] **Re-register Telegram webhook** after domain change
- [ ] **Rate limiting** — current in-memory rate limits reset per cold start; consider Vercel KV or Upstash Redis
- [ ] **Database backups** — Turso has built-in point-in-time recovery
- [ ] **Disable `/admin/*` endpoints** in production or add authentication

---

## File Structure After Changes

```
clawsafe_pay/
├── api/
│   └── index.py                    ← NEW: Vercel serverless entry point
├── vercel.json                      ← NEW: Vercel routing config
├── requirements.txt                 ← NEW: Root-level merged dependencies
├── scripts/
│   └── setup_telegram_webhook.py   ← Run after deploy to register webhook
├── backend/
│   ├── publisher_service/
│   ├── signer_service/
│   ├── user_auth/
│   ├── reviewer_service/
│   └── ...
├── frontend/
└── ...
```

---

## Quick-Start Summary

```bash
# 1. Install Vercel CLI
npm i -g vercel

# 2. Set up Turso databases
turso db create clawsafe-publisher
turso db create clawsafe-signer
turso db create clawsafe-userauth

# 3. Seed databases
turso db shell clawsafe-publisher < seed/publisher.sql
turso db shell clawsafe-signer < seed/signer.sql
turso db shell clawsafe-userauth < seed/user_auth.sql

# 4. Create vercel.json and api/index.py (see sections above)

# 5. Set all env vars in Vercel dashboard

# 6. Deploy
vercel --prod

# 7. Register Telegram webhook
python scripts/setup_telegram_webhook.py \
  --url "https://<your-app>.vercel.app/telegram/webhook"

# 8. Verify
curl "https://<your-app>.vercel.app/health"

# Done! 🎉
```

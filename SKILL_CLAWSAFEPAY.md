# ClawSafe Pay – Agent Skill

> **Purpose**: This skill lets an OpenClaw agent send payments across multiple
> blockchains via the ClawSafe Pay publisher_service API. The agent only needs
> to talk to **one service** (`publisher_service`). Everything else —
> transaction building, contract review, Telegram 2FA approval, signing, and
> broadcasting — happens automatically behind the scenes.
>
> **Currently active**: Sepolia testnet (ETH). Base L2, Solana, Bitcoin,
> Zcash, and Cardano are registered as placeholders for future activation.

---

## Quick Start

```
Base URL (local):  http://localhost:8002
Base URL (ngrok):  https://<your-subdomain>.ngrok-free.dev/publisher
Auth:              X-API-Key header (agent key from the admin dashboard)
```

> **Ngrok single-tunnel mode**: When exposed via ngrok, the frontend on
> port 8008 proxies all `/publisher/*` requests to the publisher service.
> Use the ngrok URL with a `/publisher` prefix as your base URL.

All requests and responses are JSON. Monetary values are **smallest-unit
strings** (e.g. 1 ETH = `"1000000000000000000"` wei, 1 SOL = `"1000000000"`
lamports).

---

## Endpoints

### 1. List Available Wallets

```
GET /wallets
```

No authentication required.

**Response (200 OK)**

```json
{
  "wallets": [
    "0xd77E4F8142a0C48A62601cD5Be99f591D2D515da",
    "0x52492C6B4635E6b87f2043A6Ac274Be458060b48"
  ],
  "default": "0xd77E4F8142a0C48A62601cD5Be99f591D2D515da"
}
```

Use this endpoint to discover which sender wallets are available before
submitting an intent. The `default` field shows which wallet will be used
when `from_address` is omitted.

---

### 2. Submit a Payment Intent

```
POST /intent
```

**Headers**

| Header         | Value                        |
| -------------- | ---------------------------- |
| Content-Type   | application/json             |
| X-API-Key      | `<PUBLISHER_API_KEY>`        |

**Request Body**

| Field          | Type   | Required | Description                                       |
| -------------- | ------ | -------- | ------------------------------------------------- |
| `intent_id`    | string | yes      | Unique ID you generate (e.g. `"pay-017"`)         |
| `from_user`    | string | yes      | Payer identifier (e.g. `"alice"`)                  |
| `to_user`      | string | yes      | Payee identifier (e.g. `"bob"`)                    |
| `amount_wei`   | string | yes      | Amount in smallest unit as a decimal string        |
| `to_address`   | string | yes      | Recipient address (format depends on chain)        |
| `from_address` | string | no       | Sender wallet address (default: system default wallet) |
| `chain`        | string | no       | Target chain (default `"sepolia"`)                 |
| `asset`        | string | no       | Asset to transfer (default `"ETH"`)                |
| `note`         | string | no       | Human-readable memo (default `""`)                 |
| `calldata`     | string | no       | Hex-encoded calldata for contract interactions (default `"0x"` = simple transfer) |
| `calldata_description` | string | no | Plain-English description of what the calldata does — used by the reviewer to independently verify the operation |

> **`from_address`**: Pass a wallet address returned by `GET /wallets` to
> select which wallet signs and pays for the transaction. If omitted or empty,
> the system uses the default wallet.

**Example Request**

```bash
curl -s -X POST http://localhost:8002/intent \
  -H "Content-Type: application/json" \
  -H "X-API-Key: change-me-publisher-key" \
  -d '{
    "intent_id": "pay-017",
    "from_user": "alice",
    "to_user": "bob",
    "amount_wei": "10000000000000000",
    "to_address": "0x52492C6B4635E6b87f2043A6Ac274Be458060b48",
    "from_address": "0xd77E4F8142a0C48A62601cD5Be99f591D2D515da",
    "note": "Pay Bob 0.01 ETH for coffee"
  }'
```

**Response (202 Accepted)**

```json
{
  "intent_id": "pay-017",
  "status": "pending",
  "chain": "sepolia",
  "message": "Intent received, processing started"
}
```

**Error Responses**

| Status | Meaning                | Detail                              |
| ------ | ---------------------- | ----------------------------------- |
| 401    | Bad API key            | `"Invalid API key"`                 |
| 400    | Injection detected     | Prompt-injection filter triggered   |
| 409    | Duplicate intent_id    | `"Duplicate intent_id"`             |
| 422    | Validation error       | Invalid address, missing fields     |
| 429    | Rate limited           | Max 600 requests / 60 s per IP      |

---

### 3. Poll Intent Status

```
GET /intent/{intent_id}
```

**Headers**

| Header    | Value                 |
| --------- | --------------------- |
| X-API-Key | `<PUBLISHER_API_KEY>` |

**Response (200 OK)**

```json
{
  "intent_id": "pay-017",
  "status": "confirmed",
  "from_user": "alice",
  "to_user": "bob",
  "to_address": "0x52492c6b4635e6b87f2043a6ac274be458060b48",
  "from_address": "0xd77E4F8142a0C48A62601cD5Be99f591D2D515da",
  "amount_wei": "10000000000000000",
  "chain": "sepolia",
  "asset": "ETH",
  "note": "Pay Bob 0.01 ETH for coffee",
  "created_at": "2026-03-03T12:00:00",
  "updated_at": "2026-03-03T12:00:45",
  "draft_tx": { "...": "built transaction details" },
  "review_report": { "...": "reviewer verdict & reasons" },
  "tx_hash": "0xabc123...",
  "error_message": null
}
```

**Key fields**:
- `status` — see the state machine below.
- `from_address` — the wallet that signed the transaction (empty string if
  the system default was used).

---

### 4. List All Intents

```
GET /intents
```

Returns a JSON array of all intents (newest first). Same auth header required.
Each object includes `from_address`. Useful for displaying history or checking
recent activity.

---

### 5. Health Check (no auth)

```
GET /health
```

Returns `{"status": "ok"}` when the service is running.

---

## Status State Machine

After you submit an intent, it moves through these states automatically:

```
pending
  → building          (constructing the EVM transaction)
  → reviewing         (contract/gas review)
  → signing           (waiting for Telegram 2FA approval + signing)
  → broadcast         (raw tx sent to Sepolia network)
  → confirmed         (terminal ✅ — tx_hash is set)

Failure branches (terminal ❌):
  → blocked           (reviewer said BLOCK)
  → rejected          (user rejected on Telegram)
  → expired           (user didn't respond in time)
  → failed            (build error, policy violation, sign/broadcast failure)
```

**Terminal success**: `confirmed`
**Terminal failures**: `blocked`, `rejected`, `expired`, `failed`
**In-progress**: everything else

---

## Recommended Agent Workflow

```
0.  GET /wallets  →  discover available sender wallets and the default
1.  POST /intent  →  get back intent_id + status "pending"
    (optionally pass from_address to select a specific wallet)
2.  Wait 3-5 seconds
3.  GET /intent/{intent_id}  →  check status
4.  If status is still in-progress (pending/building/reviewing/signing/broadcast):
      → wait 3-5 seconds, then poll again (step 3)
5.  If status is "confirmed":
      → success! read tx_hash from the response
6.  If status is "failed" / "blocked" / "rejected" / "expired":
      → read error_message for the reason, report failure to user
```

**Wallet selection tips**:
- Call `GET /wallets` once at startup to cache the list.
- If the user doesn't specify a sender, omit `from_address` (the default wallet will be used).
- If the user requests a specific sender, match it against the wallets list and pass it as `from_address`.

**Polling tips**:
- Poll every **3–5 seconds**. The Telegram approval step can take up to 5 minutes.
- Maximum recommended poll duration: **6 minutes** (the signer times out at ~6 min).
- Do **not** resubmit the same `intent_id` — you'll get a 409 Duplicate error.

---

## Unit Conversion Reference

| Chain    | Asset | Smallest Unit | Decimals | Example: 0.01 native          |
| -------- | ----- | ------------- | -------- | ------------------------------ |
| Sepolia  | ETH   | wei           | 18       | `"10000000000000000"`          |
| Base     | ETH   | wei           | 18       | `"10000000000000000"`          |
| Solana   | SOL   | lamports      | 9        | `"10000000"`                   |
| Bitcoin  | BTC   | satoshi       | 8        | `"1000000"`                    |
| Zcash    | ZEC   | zatoshi       | 8        | `"1000000"`                    |
| Cardano  | ADA   | lovelace      | 6        | `"10000"`                      |

Tokens (USDC, USDT) use **6 decimals** on all chains:
`1 USDC = "1000000"`

**Policy limit**: The default maximum per-transaction amount is **0.05 ETH**
(`50000000000000000` wei). Amounts above this will be rejected with a policy
violation error.

---

## Supported Chains

| Chain slug        | Family   | Status         | Native asset | Address format         |
| ----------------- | -------- | -------------- | ------------ | ---------------------- |
| `sepolia`         | EVM      | **Active**     | ETH          | `0x` + 40 hex chars    |
| `base`            | EVM      | Placeholder    | ETH          | `0x` + 40 hex chars    |
| `solana-devnet`   | Solana   | Placeholder    | SOL          | Base58 (32-44 chars)   |
| `bitcoin-testnet` | UTXO     | Placeholder    | BTC          | `m`/`n`/`tb1`…         |
| `zcash-testnet`   | UTXO     | Placeholder    | ZEC          | `tm`/`ztestsapling`…   |
| `cardano-preprod` | Cardano  | Placeholder    | ADA          | `addr_test1`…          |

## Supported Tokens

| Token  | Sepolia | Base | Solana | Transfer method |
| ------ | ------- | ---- | ------ | --------------- |
| USDC   | ✅      | ✅   | ✅     | ERC-20 / SPL    |
| USDT   | ✅      | ✅   | ✅     | ERC-20 / SPL    |

---

## Contract Interactions (DeFi, Swaps, Staking)

To interact with a smart contract — such as swapping tokens on Uniswap, staking, or calling any on-chain function — populate the `calldata` and `calldata_description` fields.

**How it works:**
1. Your agent builds the ABI-encoded calldata (using ethers.js, web3.py, etc.)
2. Submit the intent with `to_address` = the contract address, `value_wei` = ETH sent with the call (if any), and `calldata` = the encoded function call
3. The reviewer independently decodes your calldata and compares it against your `calldata_description`
4. The human approving on Telegram sees **both** your description **and** the reviewer's independent interpretation — mismatches are flagged

**Example: Uniswap V3 swap (0.01 ETH → WBTC on Sepolia)**

```bash
curl -s -X POST http://localhost:8002/intent \
  -H "Content-Type: application/json" \
  -H "X-API-Key: change-me-publisher-key" \
  -d '{
    "intent_id": "swap-001",
    "from_user": "alice",
    "to_user": "uniswap",
    "amount_wei": "10000000000000000",
    "to_address": "0x3bFA4769FB09eefC5a80d6E87c3B9C650f7Ae48",
    "calldata": "0x414bf389...",
    "calldata_description": "exactInputSingle: swap 0.01 ETH for WBTC, recipient=0xMywallet, slippage 0.5%",
    "note": "DCA buy: weekly WBTC accumulation"
  }'
```

> **Simple transfers**: Leave `calldata` unset (defaults to `"0x"`). The system behaves exactly as before — no changes needed for existing simple payment flows.

> **Gas**: Contract calls use a default gas limit of 300,000. If your operation requires more, contact the platform administrator to adjust the policy.

---

## Security Notes

- **API key** is required on every `/intent` and `/intents` call. Pass it via
  the `X-API-Key` header.
- **Prompt-injection filter**: The `note`, `from_user`, and `to_user` fields
  are scanned for injection attempts. Malicious payloads will be rejected (400).
- **Recipient allowlist**: If configured, only allowlisted `to_address` values
  are accepted. Default is `*` (any address).
- **Rate limiting**: 600 requests per minute per IP. The `/health`, `/docs`,
  and `/openapi.json` endpoints are exempt.
- **Telegram webhook security**: When using webhook mode, Telegram callbacks
  are verified via a secret token (`X-Telegram-Bot-Api-Secret-Token` header).
- The agent **never** touches private keys or signing — that's all handled
  internally by the signer_service + Telegram 2FA.

---

## Telegram Delivery Modes

The system supports **two modes** for delivering Telegram 2FA prompts:

| Mode | Env var | How it works |
| --- | --- | --- |
| **Webhook** (recommended) | `TELEGRAM_WEBHOOK_URL` set | Telegram pushes updates instantly to your URL. Auto-registered on service startup. |
| **Long-polling** (default) | `TELEGRAM_WEBHOOK_URL` empty | The service polls Telegram every few seconds. Works behind NATs, no public URL needed. |

When running behind ngrok, set `TELEGRAM_WEBHOOK_URL=https://<subdomain>.ngrok-free.dev/telegram/webhook` and the frontend proxy will forward Telegram callbacks to the user_auth service automatically.

---

## Ngrok Single-Tunnel Architecture

A single ngrok tunnel on the **frontend** port (8008) exposes everything:

```
ngrok http 8008
```

The frontend automatically proxies:

| Public path | Internal target | Purpose |
| --- | --- | --- |
| `/publisher/*` | `publisher_service:8002` | Payment API (intents, wallets, agents) |
| `/telegram/*` | `user_auth:8000` | Telegram webhook callbacks |
| `/user-auth/*` | `user_auth:8000` | Admin/health endpoints |
| `/*` | `frontend:8008` | Dashboard, pages, static assets |

This means the agent only needs **one URL** (the ngrok URL) to reach all services.

---

## Example: Full Agent Interaction

```python
import httpx, time

API = "http://localhost:8002"       # or ngrok: "https://<sub>.ngrok-free.dev/publisher"
KEY = "change-me-publisher-key"
HEADERS = {"X-API-Key": KEY}

# Step 0 — Discover wallets
wallets = httpx.get(f"{API}/wallets").json()
print(wallets)  # {"wallets": ["0x...", "0x..."], "default": "0x..."}

# Step 1 — Submit (using a specific wallet)
resp = httpx.post(f"{API}/intent", headers=HEADERS, json={
    "intent_id": "pay-042",
    "from_user": "alice",
    "to_user": "bob",
    "amount_wei": "10000000000000000",   # 0.01 ETH
    "to_address": "0x52492C6B4635E6b87f2043A6Ac274Be458060b48",
    "from_address": wallets["default"],   # or pick any from wallets["wallets"]
    "note": "Lunch reimbursement",
})
print(resp.json())  # {"intent_id": "pay-042", "status": "pending", ...}

# Step 2 — Poll until terminal
while True:
    time.sleep(4)
    status = httpx.get(f"{API}/intent/pay-042", headers=HEADERS).json()
    print(f"  status: {status['status']}")
    if status["status"] in ("confirmed", "failed", "blocked", "rejected", "expired"):
        break

# Step 3 — Report result
if status["status"] == "confirmed":
    print(f"✅ Confirmed! tx: https://sepolia.etherscan.io/tx/{status['tx_hash']}")
    print(f"   Signed by wallet: {status.get('from_address', 'default')}")
else:
    print(f"❌ {status['status']}: {status.get('error_message', 'no details')}")
```
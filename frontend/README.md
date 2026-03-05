# ClawSafe Pay — Frontend (Dashboard)

Standalone frontend service for the ClawSafe Pay demo dashboard, running on port **8008**.
Payment API calls go cross-origin to the `publisher_service` on port **8002**.
Feed proxies (crypto prices, crypto news, Moltbook) are served directly by this service.

---

## Directory Structure

```
frontend/
├── app.py                  # FastAPI app (page routes, feed proxies, static mount)
├── config.py               # Environment config (ports, publisher URL)
├── main.py                 # Uvicorn entry point (python -m frontend.main)
├── requirements.txt        # Python dependencies
├── Dockerfile              # Container image
├── __init__.py
├── index.html              # Main command-center SPA (~575 lines, HTML only)
├── homepage.html            # Professional landing page
├── security.html            # Security architecture page
├── setup_guide.html         # Setup / installation guide
├── api_users.html           # Redirect → /dashboard
├── README.md                # This file
└── src/
    ├── themes.css           # Shared CSS custom-property themes (11 themes)
    ├── dashboard.css        # Dashboard-specific styles
    ├── pages.css            # Styles for homepage / security / setup pages
    ├── theme-loader.js      # Reads theme from localStorage, injects floating picker
    ├── logo.png             # Logo image
    └── js/                  # ES module tree for the dashboard
        ├── app.js           # Entry point — imports all modules, init & polling
        ├── state.js         # Shared state object, API config, chain metadata
        ├── utils.js         # Escaping, toasts, formatters, badges, widget collapse
        ├── theme.js         # Dashboard theme switcher
        ├── transactions.js  # Transaction CRUD, filtering, table, timeline
        ├── agents.js        # Agent CRUD, selectors, key/edit modals
        ├── wallets.js       # Wallet management, balances
        ├── monitor.js       # Per-agent wallet monitor
        ├── finance.js       # Budget tracker, spend forecast, cost breakdown
        ├── feeds.js         # Crypto prices (sparklines), news, Moltbook feed
        └── particles.js     # Canvas particle background animation
```

---

## How It Works

The dashboard is a **vanilla HTML / CSS / JS** frontend with no build step. All JavaScript is split into ES modules (`type="module"`) that import from each other via relative paths.

The service is a lightweight FastAPI app (`dashboard/app.py`) that serves the HTML pages and static assets. A `/config.js` endpoint dynamically injects the publisher service URL so the frontend knows where the backend API lives.

### Serving

`frontend/app.py` serves the following routes:

| URL | File / Handler |
| --- | -------------- |
| `/` | `homepage.html` |
| `/dashboard`, `/demo` | `index.html` |
| `/setup-guide` | `setup_guide.html` |
| `/security` | `security.html` |
| `/dashboard/api-users` | `api_users.html` (redirect) |
| `/config.js` | Dynamic JS with publisher API URL |
| `/crypto-prices` | Proxy → CoinGecko API |
| `/crypto-news` | Proxy → RSS aggregation |
| `/moltbook-feed` | Proxy → Moltbook API |
| `/static/*` | `src/` directory (StaticFiles mount) |
| `/dashboard/logo.png` | `src/logo.png` |
| `/health` | Health check |

### Theming

Eleven themes are defined in `src/themes.css` as CSS custom properties.  
The active theme is persisted in `localStorage('clawsafe-theme')` and applied on load by `src/theme-loader.js` (content pages) or `src/js/theme.js` (dashboard).

Themes: **midnight** (default), slate, ocean, cloud, sand, mint, carbon, graphite, ember, sakura.

---

## Configuration

Environment variables (set in `.env` at the project root):

| Variable | Default | Description |
| -------- | ------- | ----------- |
| `DASHBOARD_PORT` | `8008` | Port the dashboard service listens on |
| `PUBLISHER_API_URL` | `http://localhost:8002` | Publisher service base URL |
| `PUBLISHER_API_KEY` | `change-me-publisher-key` | API key injected into frontend config |

---

## Local Development

### Prerequisites

- Python 3.11+ with a virtual environment
- Publisher service running on port 8002 (for API calls)

### Quick Start

```bash
# From the project root
./demo.sh            # starts all four services + opens the browser
./demo.sh stop       # tears down
```

Or start just the frontend service:

```bash
source .venv/bin/activate
pip install -r frontend/requirements.txt
python -m frontend.main
# Dashboard at http://localhost:8008/dashboard
```

### Editing

1. **HTML** — edit `index.html` (markup only, no inline CSS or JS).
2. **Styles** — edit `src/dashboard.css` for dashboard styles or `src/pages.css` for content pages. Theme variables go in `src/themes.css`.
3. **JavaScript** — edit the relevant module under `src/js/`. The entry point is `src/js/app.js`.
4. **Reload** the browser — no build step required.

### Adding a New Widget

1. Add the HTML markup inside `index.html` within the appropriate grid column.
2. Create a new module, e.g. `src/js/my-widget.js`, exporting an async fetch and a render function.
3. Import it in `src/js/app.js` and call its init in the `DOMContentLoaded` handler.
4. Expose any functions needed by inline `onclick` handlers via `window.myFunction = myFunction;`.

---

## API Dependencies

The dashboard communicates with the publisher service REST API for payment
operations, and serves feed data (crypto prices, news, Moltbook) directly:

**Publisher API (cross-origin to port 8002):**

| Method | Endpoint | Purpose |
| ------ | -------- | ------- |
| `GET` | `/intents` | List all payment intents |
| `POST` | `/intent` | Submit a new payment intent |
| `GET` | `/api-users` | List agents |
| `POST` | `/api-users` | Create agent |
| `PUT` | `/api-users/:id` | Update agent |
| `DELETE` | `/api-users/:id` | Deactivate agent |
| `POST` | `/api-users/:id/regenerate-key` | Regen API key |
| `GET` | `/api-users/:id/intents` | Agent-specific intents |
| `GET` | `/wallets` | List wallets (dropdown) |
| `GET` | `/wallets/managed` | List managed wallets |
| `POST` | `/wallets` | Add wallet |
| `DELETE` | `/wallets/:id` | Remove wallet |
| `POST` | `/wallets/:id/set-default` | Set default wallet |
| `GET` | `/wallets/balances` | Live balances |

**Frontend-local feed proxies (same origin on port 8008):**

| Method | Endpoint | Upstream |
| ------ | -------- | -------- |
| `GET` | `/crypto-prices` | CoinGecko `/coins/markets` |
| `GET` | `/crypto-news` | CoinDesk / CoinTelegraph / Binance RSS |
| `GET` | `/moltbook-feed` | Moltbook `/api/v1/posts` |

All publisher requests include the header `X-API-Key: <publisher-admin-key>`.

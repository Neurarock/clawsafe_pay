# ClawSafe Pay — Dashboard Frontend

Self-contained frontend for the ClawSafe Pay demo dashboard, served by `publisher_service` on port **8002**.

---

## Directory Structure

```
dashboard/
├── index.html              # Main command-center SPA (~570 lines, HTML only)
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

### Serving

`publisher_service/app.py` serves the dashboard:

| URL | File |
| --- | ---- |
| `/` | `homepage.html` |
| `/dashboard`, `/demo` | `index.html` |
| `/setup-guide` | `setup_guide.html` |
| `/security` | `security.html` |
| `/dashboard/api-users` | `api_users.html` (redirect) |
| `/static/*` | `src/` directory (StaticFiles mount) |
| `/dashboard/logo.png` | `src/logo.png` |

### Theming

Eleven themes are defined in `src/themes.css` as CSS custom properties.  
The active theme is persisted in `localStorage('clawsafe-theme')` and applied on load by `src/theme-loader.js` (content pages) or `src/js/theme.js` (dashboard).

Themes: **midnight** (default), slate, ocean, cloud, sand, mint, carbon, graphite, ember, sakura.

---

## Local Development

### Prerequisites

- Python 3.11+ with a virtual environment
- All service dependencies installed (see root README)

### Quick Start

```bash
# From the project root
./demo.sh            # starts all three services + opens the browser
./demo.sh stop       # tears down
```

Or start just the publisher service:

```bash
source .venv/bin/activate
python -m publisher_service.main
# Dashboard at http://localhost:8002/dashboard
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

The dashboard communicates with the publisher service REST API:

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
| `GET` | `/crypto-prices` | Top 10 crypto prices |
| `GET` | `/crypto-news` | Crypto news articles |
| `GET` | `/moltbook-feed` | Moltbook finance feed |

All requests include the header `X-API-Key: <publisher-admin-key>`.

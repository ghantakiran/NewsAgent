# NewsAgent — Real-Time Stock Market News

> Bloomberg-terminal-inspired stock market news aggregator with live feeds, analyst upgrades/downgrades, earnings tracking, and catalyst scanning. Free and self-hosted.

Aggregates real-time market news from 19 public RSS feeds into a single dark-themed interface, available as a Streamlit web app, a FastAPI-powered REST API, and a React Native mobile app for iOS and Android.

## Features

- **Live News Feed** — Real-time aggregation from 19 financial news sources (Yahoo Finance, CNBC, MarketWatch, Benzinga, Seeking Alpha, Nasdaq, and more)
- **Analyst Ratings** — Upgrades, downgrades, and initiations with quality grading (A+ to C) and price targets
- **Earnings Tracker** — EPS, revenue, and beat/miss indicators from dedicated earnings feeds
- **Catalyst Engine** — 50+ typed event classes (buyouts, FDA decisions, dilution, halts, guidance, short reports) scored 0–100 for expected impact, clustered across sources, and confirmed against the tape
- **Smart Filtering** — Noise detection removes non-trading content automatically
- **Ticker Watchlist** — Personal watchlist with push notification alerts (mobile)
- **By-Symbol View** — Articles grouped and filterable by ticker symbol
- **Dark Theme** — Bloomberg-inspired terminal UI optimized for extended monitoring
- **Squawk Tape** — a chronological, latency-first stream of catalysts as they land, with age in seconds and the source that printed it first
- **Primary Sources** — SEC 8-K/424B5 filings, Nasdaq trading halts, StockTitan and the press wires, where catalysts break before the news picks them up
- **Tiered Polling** — wires and filings polled every 10s, fast aggregators every 45s, general news every 180s, so slow sources never delay fast ones
- **Source Fan-Out** — Finviz, Seeking Alpha and Nasdaq queried per-symbol in parallel for the tickers you care about
- **Grok Live Search** *(optional)* — reads X and the web for events breaking ahead of any RSS feed, and explains unexplained moves
- **Price Confirmation** — Live quote and relative volume per catalyst, so you can tell a headline the market ignored from one it acted on
- **Zero Config** — Works out of the box with public data, no API keys needed

## Architecture

```
┌──────────────────┐     ┌──────────────────┐     ┌─────────────┐
│  React Native    │────>│  FastAPI Backend  │────>│   SQLite /  │
│  Mobile App      │<────│  (Python)         │     │  PostgreSQL │
│  iOS + Android   │     │  22 API routes    │     └─────────────┘
└──────────────────┘     └──────────────────┘
         |                       |
    Expo Push              RSS Feeds (19)
    Notifications          Background Refresh (15s)

┌──────────────────┐     ┌─────────────┐
│  Streamlit       │────>│   SQLite     │
│  Web App         │     │   (local)    │
│  (standalone)    │     └─────────────┘
└──────────────────┘
```

The Streamlit web app (`app.py`) runs standalone with its own SQLite cache. The FastAPI backend (`backend/`) serves the React Native mobile app and provides a full REST API with JWT authentication, user accounts, and push notifications.

## Quick Start

### Web App (Streamlit)

```bash
pip install -r requirements.txt
streamlit run app.py
```

Opens at `http://localhost:8501` with a dark-themed dashboard.

### Backend API

```bash
pip install -r backend/requirements.txt
python -m uvicorn backend.main:app --reload
```

API docs at `http://localhost:8000/docs` (Swagger UI).

### Mobile App

```bash
cd mobile
npm install
npx expo start
# Scan QR code with Expo Go on your device
```

### Run Tests

```bash
pip install pytest
pytest tests/ -v   # 48 tests
```

## Project Structure

```
NewsAgent/
├── app.py                      # Streamlit web app entry point
├── run.py                      # Alternative runner script
├── requirements.txt            # Streamlit app dependencies
├── src/newsagent/              # Shared core modules
│   ├── catalysts/              #   Catalyst engine (used by app.py AND the API)
│   │   ├── types.py            #     Event taxonomy: 50+ types, impact, direction
│   │   ├── detect.py           #     Detection rules, 8-K items, halt codes, facts
│   │   ├── universe.py         #     SEC ticker universe, company-name resolution
│   │   ├── market.py           #     Quotes, relative volume, provider failover
│   │   ├── engine.py           #     Clustering, scoring, orchestration
│   │   └── store.py            #     SQLite persistence, filters, alert queue
│   ├── app.py                  #   Streamlit main app logic
│   ├── models.py               #   Dataclasses (Article, Feed, UpgradeDowngrade)
│   ├── fetcher.py              #   RSS feed fetching engine
│   ├── parser.py               #   Article parsing, ticker extraction, categorization
│   ├── database.py             #   SQLite cache layer
│   ├── feeds.py                #   Feed management (add/remove/toggle)
│   └── ui/                     #   UI components and styles
│       ├── components.py       #     Streamlit UI component functions
│       └── styles.py           #     Dark theme CSS
├── backend/                    # FastAPI REST API
│   ├── main.py                 #   App entry point, lifespan, CORS
│   ├── config.py               #   Configuration and environment variables
│   ├── Dockerfile              #   Container deployment
│   ├── requirements.txt        #   Backend-specific dependencies
│   ├── alembic.ini             #   Database migration config
│   ├── core/                   #   Core infrastructure
│   │   ├── auth.py             #     JWT token handling
│   │   ├── database.py         #     SQLite connection management
│   │   ├── db_async.py         #     Async database sessions (PostgreSQL)
│   │   └── deps.py             #     FastAPI dependency injection
│   ├── models/                 #   Data models
│   │   ├── orm.py              #     SQLAlchemy ORM models
│   │   └── schemas.py          #     Pydantic request/response schemas
│   ├── routers/                #   API route handlers
│   │   ├── articles.py         #     /articles, /articles/breaking, /articles/by-symbol
│   │   ├── auth.py             #     /auth/register, /auth/login, /auth/refresh
│   │   ├── catalysts.py        #     /catalysts, /catalysts/stats, /catalysts/scan
│   │   ├── earnings.py         #     /earnings
│   │   ├── feeds.py            #     /feeds CRUD
│   │   ├── notifications.py    #     Device registration for push
│   │   ├── stats.py            #     /stats
│   │   ├── upgrades.py         #     /upgrades-downgrades
│   │   └── users.py            #     /watchlist, /settings
│   ├── services/               #   Business logic
│   │   ├── article_service.py  #     Article CRUD operations
│   │   ├── earnings_service.py #     Earnings data extraction
│   │   ├── feed_service.py     #     Feed refresh engine
│   │   ├── notification_service.py  # Push notification dispatch
│   │   ├── parser_service.py   #     Ticker/category parsing
│   │   └── ud_service.py       #     Upgrade/downgrade extraction
│   └── migrations/             #   Alembic database migrations
│       ├── env.py
│       └── versions/
├── mobile/                     # React Native Expo app
│   ├── App.tsx                 #   Root component
│   ├── app.json                #   Expo configuration
│   ├── eas.json                #   EAS Build configuration
│   ├── package.json            #   Node dependencies
│   └── src/
│       ├── api/client.ts       #     Axios/fetch API client
│       ├── components/         #     Reusable UI components
│       │   ├── ArticleCard.tsx  #       News article card
│       │   ├── EarningsCard.tsx #       Earnings result card
│       │   ├── UDRow.tsx        #       Upgrade/downgrade row
│       │   ├── FilterBar.tsx    #       Category filter chips
│       │   ├── SearchBar.tsx    #       Ticker search
│       │   ├── TickerBadge.tsx  #       Ticker symbol badge
│       │   ├── GradeBadge.tsx   #       Analyst grade indicator
│       │   ├── CategoryBadge.tsx#       Category label
│       │   ├── PulseIndicator.tsx#      Live pulse animation
│       │   ├── LoadingSkeleton.tsx#     Loading placeholder
│       │   └── ...
│       ├── screens/            #     App screens
│       │   ├── LiveFeedScreen.tsx#      Breaking/live news
│       │   ├── AllNewsScreen.tsx #      Full article list
│       │   ├── UDRatingsScreen.tsx#     Analyst ratings
│       │   ├── EarningsScreen.tsx#      Earnings results
│       │   ├── CatalystsScreen.tsx#     Catalyst events
│       │   ├── BySymbolScreen.tsx#      Articles grouped by ticker
│       │   ├── WatchlistScreen.tsx#     Personal watchlist
│       │   ├── FeedsScreen.tsx  #       RSS feed management
│       │   ├── LoginScreen.tsx  #       Authentication
│       │   ├── SettingsScreen.tsx#      App settings
│       │   └── MoreScreen.tsx   #       Additional options
│       ├── navigation/         #     React Navigation config
│       ├── hooks/              #     Custom React hooks
│       ├── store/index.ts      #     Zustand state management
│       ├── theme/              #     Dark theme constants
│       └── types/              #     TypeScript type definitions
├── config/                     # Configuration files
│   ├── settings.toml           #   App settings (refresh interval, limits)
│   └── default_feeds.toml      #   Default RSS feed list (19 feeds)
├── tests/                      # Test suite (48 tests)
│   ├── conftest.py             #   Shared fixtures
│   ├── test_api.py             #   API endpoint tests
│   ├── test_models.py          #   Data model tests
│   └── test_services.py        #   Service layer tests
├── scripts/                    # Utility scripts
│   ├── deploy.sh               #   Deployment helper
│   └── build-mobile.sh         #   Mobile build script
├── docs/                       # Documentation
│   ├── PRD.md                  #   Product requirements
│   ├── DEPLOYMENT.md           #   Deployment guide
│   ├── app-store-listing.md    #   App store listing copy
│   ├── privacy-policy.html     #   Privacy policy
│   └── terms-of-service.html   #   Terms of service
├── Procfile                    # Heroku/Railway process file
├── railway.toml                # Railway deployment config
└── render.yaml                 # Render deployment config
```

## API Endpoints

All endpoints are prefixed with `/api/v1`.

### Articles

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/articles` | Paginated article list with category/ticker filters |
| GET | `/articles/breaking` | Breaking news from the last 2 hours |
| GET | `/articles/by-symbol` | Articles grouped by ticker symbol |
| GET | `/articles/tickers` | List of all detected ticker symbols |

### Analyst Ratings

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/upgrades-downgrades` | Analyst upgrades, downgrades, initiations |
| POST | `/upgrades-downgrades/reprocess` | Re-parse articles for U/D data |

### Market Data

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/earnings` | Earnings results with EPS/revenue data |
| GET | `/stats` | System statistics (article counts, feed health) |

### Catalysts

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/catalysts` | Ranked catalyst events (see filters below) |
| GET | `/catalysts/stats` | Board summary: totals, high-impact and confirmed counts |
| GET | `/catalysts/{id}` | One catalyst with its full source list and score breakdown |
| POST | `/catalysts/scan` | Re-run detection over the cached articles immediately |
| GET | `/catalysts/grok/status` | Whether Grok live search is configured |
| POST | `/catalysts/grok/squawk` | Sweep X and the web for breaking events now |
| GET | `/catalysts/{id}/explain` | Ask Grok what is moving this name, with citations |

`GET /catalysts` filters: `type` (a catalyst type or a legacy category like `fda`/`m&a`),
`group` (`deal`, `clinical`, `capital`, `operating`, `legal`, `analyst`, `structural`, `macro`),
`direction` (`bullish`/`bearish`/`neutral`), `ticker`, `search`, `min_score`,
`confirmed_only`, `order` (`score`/`time`/`move`), `hours`, `limit`.

```bash
# Everything the tape has confirmed in the last 6 hours, biggest move first
curl "localhost:8000/api/v1/catalysts?confirmed_only=true&order=move&hours=6"
```

### Feeds

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/feeds` | List all RSS feeds with status |
| POST | `/feeds/custom` | Add a custom RSS feed |
| DELETE | `/feeds/custom/{name}` | Remove a custom feed |
| PATCH | `/feeds/custom/{name}` | Update a custom feed |

### Authentication

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/auth/register` | Create a new account |
| POST | `/auth/login` | Login, returns JWT tokens |
| POST | `/auth/refresh` | Refresh an expired token |

### User

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/user/watchlist` | Get user's ticker watchlist |
| PUT | `/user/watchlist` | Update watchlist |
| GET | `/user/settings` | Get user preferences |
| PUT | `/user/settings` | Update user preferences |

### Notifications

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/notifications/register-device` | Register device for push notifications |
| DELETE | `/notifications/unregister-device` | Unregister device |

### Live Alerts (TradingView)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/webhook/tradingview?token=<secret>` | Inbound TradingView alert webhook (JSON or plain text) |
| GET | `/alerts` | Backfill recent coalesced alert groups (`hours` 1-168 default 24, `limit` 1-500 default 100) |
| WS | `/ws/live?tickers=AAPL,NVDA` | Live alert stream (optional `tickers` filter) |

A single-file live dashboard is served at `GET /dashboard` (no `/api/v1` prefix). See [Live Alerts](#live-alerts-tradingview--dashboard) below.

## Live Alerts (TradingView → Dashboard)

NewsAgent can ingest live alerts from TradingView and stream them to a real-time dashboard. Fire alerts from any TradingView indicator or price condition into NewsAgent's webhook, then watch them land on the dashboard as they happen.

### 1. Set the webhook token

Set a long random secret on the backend:

```bash
TRADINGVIEW_WEBHOOK_TOKEN=$(python3 -c "import secrets; print(secrets.token_hex(32))")
```

If `TRADINGVIEW_WEBHOOK_TOKEN` is unset, the webhook endpoint returns `503`. The token is passed as a `?token=` query parameter (TradingView's free tier can't send custom headers) and is compared in constant time.

### 2. Point TradingView at the webhook

In the TradingView alert dialog, enable **Webhook URL** and set it to:

```
https://<your-backend-host>/api/v1/webhook/tradingview?token=<secret>
```

The URL must be HTTPS-reachable from TradingView's servers (no localhost).

### 3. Set the alert message

JSON bodies are preferred. Use this as the alert message template:

```json
{
  "ticker": "{{ticker}}",
  "category": "breakout",
  "signal": "{{strategy.order.action}}",
  "timeframe": "{{interval}}",
  "price": {{close}},
  "message": "{{exchange}}:{{ticker}} fired on {{interval}}"
}
```

Accepted fields: `ticker`, `category`, `signal`, `timeframe`, `price`, `message`. Aliases are also accepted: `symbol` → `ticker`, `action` → `signal`, `tf` → `timeframe`, `msg` → `message`. A plain-text body is also accepted and lands in `message`. Request bodies are capped at 16 KB.

### 4. Open the dashboard

Browse to `https://<your-backend-host>/dashboard`. The single-file dashboard (`backend/static/dashboard.html`) opens the live WebSocket, backfills recent groups via `GET /api/v1/alerts`, and renders one card per alert group (keyed by `group_id`).

To consume the stream directly, connect to the WebSocket:

```
wss://<your-backend-host>/api/v1/ws/live?tickers=AAPL,NVDA
```

Messages are JSON: `{ "type": "alert", "event": "new" | "update", "data": { ...group } }`.

### How coalescing works

A burst of alerts sharing the same **group key** (default `category,ticker`) within `COALESCE_WINDOW_SECONDS` (default `60`) collapses into a single updating card (an "episode") instead of N separate rows. As more alerts arrive in the window, the card's count increments, the latest values refresh, and the alert is appended to the group's history (capped at `ALERT_HISTORY_LIMIT`). This keeps a noisy strategy from flooding the dashboard. Coalesced groups are pruned after `ALERT_PRUNE_AFTER_DAYS`.

Set `TRADINGVIEW_FORWARD_DISCORD=true` to also forward inbound TradingView alerts to the configured per-category Discord routes.

## Default News Sources

| Source | Category | Coverage |
|--------|----------|----------|
| Yahoo Finance | General | Broad market news |
| MarketWatch | General | Top stories, analysis |
| CNBC Top News | General | Breaking business news |
| CNBC Earnings | Earnings | Quarterly results |
| Investing.com | General | Global markets |
| Benzinga | General | Analyst ratings, movers |
| Nasdaq Markets | General | Market alerts |
| Nasdaq Earnings | Earnings | Earnings reports |
| Seeking Alpha | General | Market news, analysis |
| Google News | U/D, Earnings | Analyst ratings, earnings |
| FinTwit Research | General | Social sentiment |

**Primary catalyst sources** — where events break first, before any outlet rewrites them:

Latency, not breadth, is what makes a squawk box useful, so sources are grouped
into tiers and each is polled at its own rate (`fanout.TIER_INTERVALS`):

| Tier | Interval | Sources |
|------|----------|---------|
| `flash` | 10s | SEC 8-K/424B5, Nasdaq halts, Business Wire, PR Newswire, StockTitan, FDA |
| `fast` | 45s | Finviz, MarketWatch real-time headlines and market pulse |
| `steady` | 180s | Yahoo, CNBC, Benzinga, Investing.com, Google News roundups |


| Source | Category | Coverage |
|--------|----------|----------|
| SEC EDGAR 8-K | Filing | Live filings, parsed by Item code (delisting, dilution, control change, auditor change, restatement) |
| SEC EDGAR 424B5 | Filing | Shelf takedowns — the dilution nobody announces |
| Nasdaq Trading Halts | Filing | T1 news-pending and volatility halts, with reason codes |
| Business Wire | General | Company press releases |
| PR Newswire | General | Company press releases |
| GlobeNewswire | General | Company press releases (off by default — the host throttles pollers to a timeout) |
| FDA | FDA | Drug approvals, decisions |
| StockTitan | General | Company press releases, ticker in the headline |
| Finviz | General | Curated market news, parsed from HTML (no RSS); links to the original publisher |
| MarketWatch Real-Time | General | Headline tape |

**Per-symbol fan-out** — for watchlist tickers and whatever is currently topping
the board, these are queried in parallel so a live story gets every angle:
Finviz's per-ticker page, Seeking Alpha, and Nasdaq.

Additional feeds can be added via the RSS Feeds tab (web) or the API.

## Catalyst Engine

A news feed tells you what was published. A catalyst board tells you what changed,
for which company, how much it should matter, and whether the market agrees.
The engine (`src/newsagent/catalysts/`) runs the same pipeline for both the
Streamlit app and the REST API:

```
articles ─▶ detect type ─▶ resolve ticker ─▶ cluster into events
         ─▶ attach quote ─▶ score 0-100 ─▶ rank
```

**Detection.** ~150 ordered rules across 50+ event types, plus two structured
paths that skip prose entirely: SEC 8-K **Item codes** (`Item 3.01` *is* a
delisting notice — no inference needed) and Nasdaq **halt reason codes**.
Roundup headlines ("upgrades/downgrades: AMD, DELL, ASAN") are dropped rather
than pinned on whichever ticker is listed first.

**Ticker resolution.** Validated against SEC's `company_tickers.json` (~10k
issuers, cached weekly), so a symbol has to be real. Company names resolve too —
"Sarepta Therapeutics announces…" becomes SRPT even when the headline never
prints a symbol — guarded by proper-noun and subject-position checks so
"new restaurant brands" doesn't become QSR. On a rating action the sell-side
firm is stripped first: "Goldman Sachs upgrades Apple" is news about AAPL.

**Clustering.** Six outlets rewriting one FDA approval collapse into a single
event with six sources, and that corroboration feeds back into the score.

**Scoring.** A base impact per event type, adjusted by match confidence, ticker
certainty, source authority (a filing outranks an aggregator), freshness,
corroboration, float sensitivity, and price action. Hover any score chip in the
UI for the full derivation.

**Price confirmation.** Each ranked ticker gets a live quote and its volume
versus a 20-day average. A move that agrees with the catalyst's direction earns
a `CONFIRMED` badge; one that contradicts it is marked down. Quotes come from
Yahoo with a Nasdaq fallback, and an implausible move (>50% in a session) is
cross-checked against the second provider before it is published — unadjusted
corporate actions otherwise read as a -90% collapse.

**Alerting.** Catalysts scoring `CATALYST_ALERT_MIN_SCORE` (default 70) post
once to Discord, routed by group. Never twice, and never a low-conviction event.

**Freshness.** Each scan rewrites its window rather than appending to it, so
improving ticker resolution corrects existing rows instead of leaving the old
interpretation behind as a duplicate.

## Grok (optional)

RSS can only carry what someone already published. The fastest market news —
a halt, a leak, a filing somebody spotted — breaks on X first and reaches a wire
minutes later. With `XAI_API_KEY` set, Grok's live `x_search` and `web_search`
fill that gap two ways:

- **As a source.** A periodic sweep asks for market-moving events from the last
  30 minutes and returns them as ordinary news items, so they are detected,
  scored and clustered exactly like a wire story — and merge with the wire story
  when it lands.
- **As an explainer.** "Why is this moving?" for a ticker that jumped with no
  catalyst the engine could find, answered with citations.

```bash
export XAI_API_KEY=xai-...        # enables both; everything works without it
```

| Variable | Default | Purpose |
|----------|---------|---------|
| `XAI_API_KEY` | — | Enables Grok. Unset means every Grok path is skipped. |
| `XAI_MODEL` | `grok-4.6` | Model used for search calls |
| `GROK_SQUAWK_ENABLED` | `true` | Run the periodic X sweep |
| `GROK_SQUAWK_INTERVAL` | `120` | Seconds between sweeps |
| `GROK_SQUAWK_WINDOW_MINUTES` | `30` | How far back each sweep looks |
| `TICKER_FANOUT_INTERVAL` | `90` | Seconds between per-symbol fan-outs |
| `TICKER_FANOUT_MAX` | `10` | Symbols per fan-out |

API: `GET /catalysts/grok/status`, `POST /catalysts/grok/squawk`,
`GET /catalysts/{id}/explain`.

## Configuration

Edit `config/settings.toml`:

```toml
[general]
refresh_interval = 15  # seconds
max_articles = 500
prune_after_days = 7

[ui]
theme = "dark"
articles_per_page = 50
```

Catalyst behaviour is environment-driven (backend):

| Variable | Default | Purpose |
|----------|---------|---------|
| `CATALYST_ALERTS_ENABLED` | `true` | Post high-impact catalysts to Discord |
| `CATALYST_ALERT_MIN_SCORE` | `70` | Score at or above which a catalyst alerts |
| `CATALYST_ALERT_MAX_AGE_HOURS` | `6` | Never alert on an event older than this |

## Tech Stack

### Backend (Streamlit App)
- Python 3.11+, Streamlit, feedparser, httpx, BeautifulSoup4
- SQLite (local cache), APScheduler (background refresh)

### Backend (FastAPI API)
- Python 3.12, FastAPI, uvicorn
- SQLAlchemy 2.0 (async), SQLite / PostgreSQL, Alembic migrations
- feedparser, httpx, BeautifulSoup4
- JWT authentication (python-jose, passlib with bcrypt)

### Mobile
- React Native 0.83 + Expo SDK 55 (TypeScript)
- React Navigation (bottom tabs + stack navigator)
- TanStack React Query (15s auto-refetch)
- Zustand (state management)
- expo-notifications (push), expo-haptics, expo-secure-store

### Deployment
- Backend: Railway / Render (Dockerfile, Procfile, railway.toml, render.yaml included)
- Mobile: EAS Build + EAS Submit (eas.json included)

## Deployment

See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for the full deployment guide.

Quick deploy to Railway:

```bash
# Install Railway CLI
npm i -g @railway/cli

# Deploy
railway login
railway init
railway up
```

## License

MIT

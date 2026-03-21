# NewsAgent

A fast, minimalistic stock market news aggregator. Think Newsquawk/LiveSquawk — but free and self-hosted.

Aggregates real-time market news, analyst upgrades/downgrades, and trading catalysts from public RSS feeds into a single dark-themed dashboard.

## Features

- **Live News Feed** — Real-time aggregated financial news from 10+ sources
- **Upgrades & Downgrades** — Track analyst rating changes with price targets
- **Catalyst Scanner** — Earnings, FDA decisions, M&A, insider trading events
- **Custom RSS Feeds** — Add your own feeds or use the curated defaults
- **Ticker Watchlist** — Filter everything by your tickers of interest
- **Zero Config** — Works out of the box with public RSS feeds, no API keys needed

## Quick Start

```bash
# Clone
git clone <repo-url> && cd NewsAgent

# Install dependencies
pip install -r requirements.txt

# Run
streamlit run app.py
```

Opens at `http://localhost:8501` with a dark-themed dashboard.

## Screenshots

```
┌─────────────────────────────────────────────────────┐
│  NewsAgent              [AAPL] [Add+]   [⟳ 30s]    │
├──────────┬──────────┬──────────┬────────────────────│
│  Feed    │  U/D     │  Catalysts│  RSS Feeds        │
├──────────┴──────────┴──────────┴────────────────────│
│ 12:45  AAPL  Apple beats Q4 est...      [Earnings]  │
│ 12:44  NVDA  Goldman upgrades...        [Upgrade]   │
│ 12:43  SPY   Fed signals pause...       [Macro]     │
└─────────────────────────────────────────────────────┘
```

## Default News Sources

| Source | Coverage |
|--------|----------|
| Yahoo Finance | Broad market news |
| MarketWatch | Top stories, analysis |
| CNBC | Breaking business news |
| Investing.com | Global markets |
| Benzinga | Analyst ratings, movers |
| Nasdaq | Alerts, regulatory |
| SEC EDGAR | 8-K filings |
| FDA | Drug approvals, decisions |

## Configuration

Edit `config/settings.toml` to customize:

```toml
[general]
refresh_interval = 30  # seconds
max_articles = 500
prune_after_days = 7

[ui]
theme = "dark"
articles_per_page = 50
```

Add custom feeds in `config/default_feeds.toml` or via the RSS Feeds tab in the UI.

## Tech Stack

- Python 3.11+
- Streamlit (UI)
- feedparser (RSS)
- httpx (HTTP)
- SQLite (local cache)

## License

MIT

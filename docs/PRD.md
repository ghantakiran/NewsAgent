# Product Requirements Document: NewsAgent

## Overview

**NewsAgent** is a real-time stock market news aggregator inspired by Newsquawk/LiveSquawk. It provides traders with a fast, minimalistic interface to monitor market-moving news, analyst upgrades/downgrades, catalysts, and custom RSS feeds — all in one place.

## Problem Statement

Active traders need rapid access to market-moving information from multiple sources. Existing solutions are either:
- **Too expensive** (Newsquawk ~$50-100/mo, Bloomberg Terminal ~$2k/mo)
- **Too cluttered** (financial news sites with ads, popups, irrelevant content)
- **Too slow** (manual checking of multiple RSS feeds and news sites)

NewsAgent solves this by aggregating free, high-quality financial news sources into a single, fast, distraction-free interface.

## Target Users

- Active day traders and swing traders
- Retail investors monitoring catalysts
- Anyone needing a consolidated market news dashboard

## Core Features

### 1. Live News Feed (Priority: P0)
- Real-time aggregated news from multiple financial RSS sources
- Auto-refresh with configurable interval (10s, 30s, 1m, 5m)
- Color-coded urgency/category tags (Earnings, FDA, Macro, M&A, etc.)
- Ticker symbol extraction and highlighting
- Click-through to original source
- Newest-first chronological ordering

### 2. Upgrades & Downgrades Tracker (Priority: P0)
- Dedicated feed for analyst rating changes
- Displays: Ticker, Analyst Firm, Old Rating → New Rating, Price Target
- Filter by ticker or firm
- Source: Benzinga, MarketWatch, Yahoo Finance RSS

### 3. Catalyst Scanner (Priority: P1)
- Tracks market-moving events: earnings dates, FDA decisions, ex-dividend dates
- Categories: Earnings, FDA/Biotech, Dividends, Splits, IPOs, SPACs, Insider Trading
- Filterable by category and ticker

### 4. Custom RSS Feed Manager (Priority: P1)
- Add/remove custom RSS feed URLs
- Pre-loaded with curated financial RSS feeds
- Per-feed enable/disable toggle
- Feed health status indicator (last fetch time, error state)

### 5. Ticker Watchlist & Filter (Priority: P1)
- Maintain a personal watchlist of tickers
- Filter all feeds to show only watchlist tickers
- Quick-add ticker from any news item

### 6. Search & Filter (Priority: P2)
- Full-text search across all fetched articles
- Filter by source, category, date range
- Keyword alerts (highlight matching terms)

## Architecture

### Tech Stack
| Component | Technology |
|-----------|-----------|
| Language | Python 3.11+ |
| UI Framework | Streamlit |
| RSS Parsing | feedparser |
| HTTP Client | httpx |
| HTML Parsing | beautifulsoup4 |
| Data Storage | SQLite (local cache) |
| Scheduling | APScheduler |
| Config | TOML / .env |

### Data Sources (Default RSS Feeds)

#### General Market News
- Yahoo Finance: `https://finance.yahoo.com/news/rssindex`
- MarketWatch: `http://feeds.marketwatch.com/marketwatch/topstories/`
- CNBC: `https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114`
- Reuters Business: `http://feeds.reuters.com/reuters/businessNews`
- Investing.com: `https://www.investing.com/rss/news.rss`

#### Upgrades/Downgrades
- Benzinga Analyst Ratings: `https://www.benzinga.com/feeds/analyst-ratings`
- Yahoo Finance (filtered for upgrade/downgrade keywords)

#### Sector-Specific
- FDA News: `https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds`
- SEC EDGAR Filings: `https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&type=8-K&dateb=&owner=include&count=40&search_text=&action=getcompany&RSS`

### Data Flow
```
RSS Sources ──► Fetcher ──► Parser ──► Categorizer ──► SQLite Cache
                  │                                        │
                  │ (every N seconds)                      │
                  ▼                                        ▼
            Error Handler                          Streamlit UI
                                                   ├── Live Feed
                                                   ├── Upgrades/Downgrades
                                                   ├── Catalysts
                                                   └── RSS Manager
```

### Project Structure
```
NewsAgent/
├── CLAUDE.md
├── README.md
├── pyproject.toml
├── requirements.txt
├── .env.example
├── docs/
│   └── PRD.md
├── config/
│   ├── default_feeds.toml
│   └── settings.toml
├── src/
│   └── newsagent/
│       ├── __init__.py
│       ├── app.py              # Streamlit entry point
│       ├── models.py           # Data models
│       ├── fetcher.py          # RSS/news fetching engine
│       ├── parser.py           # Article parsing & categorization
│       ├── database.py         # SQLite cache layer
│       ├── feeds.py            # Feed management
│       └── ui/
│           ├── __init__.py
│           ├── components.py   # Reusable UI components
│           ├── styles.py       # CSS/theme
│           └── pages.py        # Page layouts
├── tests/
│   ├── __init__.py
│   ├── test_fetcher.py
│   ├── test_parser.py
│   └── test_database.py
└── data/
    └── newsagent.db            # SQLite database (auto-created)
```

## UI Design

### Design Principles
- **Dark theme** — easy on the eyes for extended monitoring
- **Information density** — maximize useful data per pixel
- **Zero chrome** — no decorative elements, just data
- **Speed** — sub-second perceived load times
- **Scannable** — color-coded categories, bold tickers, timestamp prominence

### Layout
```
┌─────────────────────────────────────────────────────────┐
│  🔴 NewsAgent          [AAPL] [Add Ticker+] [⟳ 30s ▾]  │
├──────────┬──────────┬──────────┬───────────────────────│
│ 📰 Feed  │ 📊 U/D   │ ⚡ Cat   │ 📡 RSS               │
├──────────┴──────────┴──────────┴───────────────────────│
│ [Search...                        ] [All ▾] [Today ▾] │
├─────────────────────────────────────────────────────────│
│ 12:45:03  AAPL  Apple beats Q4 estimates...   [Earnings]│
│ 12:44:58  NVDA  Goldman upgrades to Buy...    [Upgrade] │
│ 12:44:12  SPY   Fed signals rate pause...     [Macro]   │
│ 12:43:55  TSLA  Tesla delivery numbers...     [Catalyst]│
│ 12:43:01  AMZN  AWS announces new AI...       [Tech]    │
│ ...                                                     │
└─────────────────────────────────────────────────────────┘
```

### Color Coding
| Category | Color |
|----------|-------|
| Earnings | 🟡 Gold |
| Upgrade | 🟢 Green |
| Downgrade | 🔴 Red |
| Macro/Fed | 🔵 Blue |
| FDA/Biotech | 🟣 Purple |
| M&A | 🟠 Orange |
| General | ⚪ Gray |

## Non-Functional Requirements

- **Refresh Rate**: Configurable 10s-5m, default 30s
- **Startup Time**: < 3 seconds to first content
- **Memory**: < 200MB RAM
- **Storage**: SQLite DB capped at 50MB (auto-prune articles > 7 days)
- **Offline**: Gracefully degrade, show cached content
- **No API Keys Required**: Works out-of-box with public RSS feeds only

## Future Enhancements (v2)
- Audio squawk alerts for high-priority news
- Push notifications via webhook (Discord, Slack, Telegram)
- Sentiment analysis on headlines
- Options flow integration
- Dark pool / unusual volume alerts
- Mobile-responsive PWA mode

## Success Metrics
- Time from news publication to display: < 60 seconds
- Zero required configuration to start
- Works with `pip install` + single command

## Version
- **v1.0** — MVP with Live Feed, Upgrades/Downgrades, Catalysts, RSS Manager
- **Target**: Functional single-user desktop application

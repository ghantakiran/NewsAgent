# CLAUDE.md — NewsAgent

## Project Overview
NewsAgent is a real-time stock market news aggregator (SquawkBox-style). Python + Streamlit app that pulls from RSS feeds to surface market-moving news, analyst upgrades/downgrades, and catalysts in a minimalistic dark UI.

## Tech Stack
- **Python 3.11+**
- **Streamlit** — UI framework
- **feedparser** — RSS/Atom parsing
- **httpx** — async HTTP client
- **beautifulsoup4** — HTML content parsing
- **SQLite** — local article cache
- **APScheduler** — background feed refresh

## Project Structure
```
src/newsagent/       — all application code
  app.py             — Streamlit entry point (run with: streamlit run app.py)
  models.py          — dataclasses for Article, Feed, UpgradeDowngrade
  fetcher.py         — RSS feed fetching engine
  parser.py          — article parsing, ticker extraction, categorization
  database.py        — SQLite cache layer
  feeds.py           — feed management (add/remove/toggle)
  ui/                — UI components, styles, page layouts
config/              — TOML config files (default feeds, settings)
data/                — SQLite DB (auto-created, gitignored)
docs/PRD.md          — product requirements
tests/               — pytest tests
```

## Commands
```bash
# Install
pip install -r requirements.txt

# Run
streamlit run app.py

# Test
pytest tests/ -v

# Lint
ruff check src/
```

## Conventions
- Use dataclasses for models, not Pydantic (keep deps minimal)
- All RSS fetching goes through `fetcher.py` — never fetch directly in UI code
- SQLite is the single source of truth for displayed articles
- UI components are pure functions that take data and return Streamlit elements
- Use `httpx` with timeout=10s for all HTTP requests
- Category detection uses keyword matching in `parser.py`
- Ticker extraction uses regex pattern `\b[A-Z]{1,5}\b` with common-word exclusion list
- Dark theme CSS lives in `ui/styles.py`
- Config uses TOML files in `config/` directory

## Important Patterns
- Feed refresh runs in background thread via APScheduler, not Streamlit's native rerun
- Articles older than 7 days auto-pruned from SQLite on startup
- All timestamps stored as UTC, displayed in local time
- RSS feed errors are caught and logged, never crash the UI
- Use `st.session_state` for watchlist and filter state

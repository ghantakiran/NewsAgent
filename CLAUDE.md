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
app.py               — Streamlit app (self-contained; run with: streamlit run app.py)
src/newsagent/       — shared library code
  catalysts/         — catalyst engine, imported by BOTH app.py and backend/
    types.py         —   event taxonomy: CatalystType, impact weight, direction
    detect.py        —   detection rules, 8-K item codes, halt codes, fact extraction
    universe.py      —   SEC ticker universe, company-name -> ticker resolution
    market.py        —   quotes, relative volume, provider failover
    engine.py        —   clustering, scoring, orchestration
    store.py         —   SQLite persistence, filtering, alert queue
    sources.py       —   source adapters: RSS plus Finviz HTML (no RSS exists)
    fanout.py        —   tiered polling + parallel per-symbol fan-out
    grok.py          —   optional xAI live X/web search (source + explainer)
  models.py          — dataclasses for Article, Feed, UpgradeDowngrade
  fetcher.py         — RSS feed fetching engine
  parser.py          — article parsing, ticker extraction, categorization
  database.py        — SQLite cache layer
  feeds.py           — feed management (add/remove/toggle)
  ui/                — UI components, styles, page layouts
backend/             — FastAPI REST API (mobile app + integrations)
config/              — TOML config files (default feeds, settings)
data/                — SQLite DB + cached ticker universe (auto-created, gitignored)
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
- Legacy ticker extraction in `app.py` uses `\b[A-Z]{1,5}\b` with an exclusion
  list; catalyst code uses `TickerUniverse` instead (SEC-validated)
- Dark theme CSS lives in `ui/styles.py`
- Config uses TOML files in `config/` directory

## Catalyst Engine
- The engine in `src/newsagent/catalysts/` is the single implementation — the
  Streamlit app and the FastAPI backend both import it, so a scoring change
  applies to both. Never fork detection logic into `app.py` or `backend/`.
- `types.py` is the source of truth for what a catalyst *is*. Adding an event
  type means adding a `CatalystType` member and a `SPECS` entry (both required —
  a test asserts every type has a spec), then rules in `detect.py`.
- Detection rules are ordered `(type, compiled regex, confidence)` tuples. Match
  the headline at full weight and the summary at a discount; never lower a
  rule's confidence to express "this event matters less" — that is `impact` in
  `types.py`.
- Structured feeds bypass the prose rules: SEC 8-K Item codes and Nasdaq halt
  reason codes state the event outright and are always more reliable.
- Ticker extraction must go through `TickerUniverse` so symbols are validated
  against SEC's listed universe. Do not add bare `[A-Z]{1,5}` regex matching.
- Scoring factors are multiplicative and each is recorded in `score_parts`, which
  the UI renders as the hover explanation. A new factor must be explainable.
- Quotes are a bonus signal, never a dependency: every provider failure degrades
  to "no quote" and the catalyst still scores.
- Latency is the product. Sources are tiered in `fanout.py` (flash 10s / fast
  45s / steady 180s) so wires and filings are never delayed behind general news.
  New feeds are tiered by name; check `tier_for` when adding one.
- Aggregators must credit the original publisher, not themselves — a Reuters
  story surfaced by Finviz has `source="Reuters"`, which is what source-authority
  scoring depends on. Adapters set this via the entry's `_source` key.
- Grok is strictly optional. Without `XAI_API_KEY` every entry point returns
  empty and nothing else changes; never make a code path depend on it.
- Each scan rewrites its window via `prune_stale_catalysts`, so the board equals
  the current analysis. Do not assume a catalyst row survives re-analysis.

## Important Patterns
- Feed refresh runs in a background thread, not Streamlit's native rerun; feeds
  are fetched concurrently because one slow wire would otherwise hold the fetch
  lock past the refresh interval and starve the thread rendering the page
- Startup runs a quote-free catalyst pass so the board paints immediately; the
  background refresher attaches prices and rescores on the next cycle
- SEC rejects terse User-Agents with a 403 — `feed_user_agent()` sends a
  descriptive one for `sec.gov` requests
- Articles older than 7 days auto-pruned from SQLite on startup
- All timestamps stored as UTC, displayed in local time
- RSS feed errors are caught and logged, never crash the UI
- Use `st.session_state` for watchlist and filter state

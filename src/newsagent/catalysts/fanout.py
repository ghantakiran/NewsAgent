"""Parallel source fan-out, tiered by how fast each source breaks news.

A squawk box is judged on latency, and not every source deserves the same
polling rate. Press wires, SEC filings and the halt tape carry catalysts the
moment they happen; broad market aggregators mostly re-report what those already
said. Polling all of them on one interval means the fast sources wait behind the
slow ones, so sources are grouped into tiers and each tier gets its own cadence:

    FLASH  (~10s)  wires, SEC, halts, StockTitan — where catalysts originate
    FAST   (~45s)  Finviz, real-time headline feeds — fast aggregation
    STEADY (~180s) general market news, analyst-rating roundups

Fan-out runs two ways: `fetch_tier` sweeps the broad sources for a tier, and
`fanout_tickers` pulls every angle on a specific list of symbols at once.
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

from . import sources as S
from .sources import NewsItem

logger = logging.getLogger("newsagent.catalysts.fanout")

MAX_WORKERS = 8
DEFAULT_PER_SOURCE_LIMIT = 40


class Tier(str, Enum):
    FLASH = "flash"
    FAST = "fast"
    STEADY = "steady"


TIER_INTERVALS = {Tier.FLASH: 10, Tier.FAST: 45, Tier.STEADY: 180}

# Sources whose names mark them as origin points rather than re-reporters.
_FLASH_MARKERS = (
    "sec ", "edgar", "8-k", "424b5", "halt", "stocktitan", "business wire",
    "businesswire", "pr newswire", "prnewswire", "globenewswire", "accesswire",
    "fda",
)
_FAST_MARKERS = ("finviz", "real-time", "realtime", "market pulse", "marketpulse", "breaking")


def tier_for(feed_name: str, category: str = "") -> Tier:
    """Which cadence a feed belongs to, inferred from its name and category."""
    name = (feed_name or "").lower()
    if any(marker in name for marker in _FLASH_MARKERS) or category == "filing":
        return Tier.FLASH
    if any(marker in name for marker in _FAST_MARKERS):
        return Tier.FAST
    return Tier.STEADY


# ── Per-ticker fan-out ───────────────────────────────────────────────

@dataclass(frozen=True)
class TickerSource:
    name: str
    url_template: str  # empty means a custom adapter


TICKER_SOURCES = (
    TickerSource("Finviz", ""),  # HTML, handled directly
    TickerSource("Seeking Alpha", "https://seekingalpha.com/api/sa/combined/{ticker}.xml"),
    TickerSource("Nasdaq", "https://www.nasdaq.com/feed/rssoutbound?symbol={ticker}"),
)


def _fetch_one_ticker_source(
    ticker: str, source: TickerSource, client, limit: int
) -> list[NewsItem]:
    try:
        if not source.url_template:
            return S.fetch_finviz_ticker(ticker, client=client, limit=limit)
        return S.fetch_rss(
            source.url_template.format(ticker=ticker.upper()),
            source.name, client=client, limit=limit, ticker_hint=ticker.upper(),
        )
    except Exception as exc:
        logger.debug("%s failed for %s: %s", source.name, ticker, exc)
        return []


def fanout_tickers(
    tickers: list[str],
    limit_per_source: int = 20,
    max_tickers: int = 12,
    workers: int = MAX_WORKERS,
) -> list[NewsItem]:
    """Every angle on each symbol, fetched concurrently and deduplicated.

    Capped at `max_tickers` so a long watchlist cannot turn one refresh into
    hundreds of requests; callers pass symbols in priority order.
    """
    wanted = list(dict.fromkeys(t.upper() for t in tickers if t))[:max_tickers]
    if not wanted:
        return []

    jobs = [(t, src) for t in wanted for src in TICKER_SOURCES]
    items: list[NewsItem] = []
    with (
        S.make_client() as client,
        ThreadPoolExecutor(max_workers=min(workers, len(jobs))) as pool,
    ):
        futures = {
            pool.submit(_fetch_one_ticker_source, t, src, client, limit_per_source): (t, src.name)
            for t, src in jobs
        }
        for future in as_completed(futures):
            try:
                items.extend(future.result())
            except Exception as exc:
                logger.debug("fan-out job %s failed: %s", futures[future], exc)
    return dedupe(items)


# ── Broad fan-out ────────────────────────────────────────────────────

def fetch_sources(feeds: list[dict], workers: int = MAX_WORKERS,
                  limit: int = DEFAULT_PER_SOURCE_LIMIT) -> list[NewsItem]:
    """Fetch a list of `{name, url, category}` feeds concurrently.

    A feed whose name marks it as Finviz uses the HTML adapter; everything else
    is RSS. Failures are logged and skipped — one dead wire never stalls a sweep.
    """
    enabled = [f for f in feeds if f.get("enabled", True)]
    if not enabled:
        return []

    def run(feed: dict) -> list[NewsItem]:
        try:
            if "finviz" in feed["name"].lower() and "quote" not in feed.get("url", ""):
                return S.fetch_finviz_news(client=None, limit=limit)
            return S.fetch_rss(feed["url"], feed["name"], limit=limit)
        except Exception as exc:
            logger.debug("source %s failed: %s", feed.get("name"), exc)
            return []

    items: list[NewsItem] = []
    with ThreadPoolExecutor(max_workers=min(workers, len(enabled))) as pool:
        for future in as_completed([pool.submit(run, f) for f in enabled]):
            try:
                items.extend(future.result())
            except Exception as exc:
                logger.debug("fan-out source failed: %s", exc)
    return dedupe(items)


def dedupe(items: list[NewsItem]) -> list[NewsItem]:
    """Drop repeats, keeping the earliest sighting of each story.

    Latency is the whole point: when two sources carry the same headline, the
    timestamp that matters is whoever printed it first.
    """
    best: dict[str, NewsItem] = {}
    for item in items:
        key = item.url or f"{item.source}|{item.title}"
        current = best.get(key)
        if current is None or item.published < current.published:
            best[key] = item
    return sorted(best.values(), key=lambda i: i.published, reverse=True)


# ── Scheduling ───────────────────────────────────────────────────────

class TieredScheduler:
    """Tracks which tiers are due, so each cadence runs at its own rate."""

    def __init__(self, intervals: dict[Tier, int] | None = None):
        self.intervals = dict(intervals or TIER_INTERVALS)
        self._last: dict[Tier, float] = {}

    # A tier that has never run is due immediately, whatever the clock reads.
    NEVER = float("-inf")

    def due(self, now: float | None = None) -> list[Tier]:
        now = now if now is not None else time.monotonic()
        return [
            tier for tier, interval in self.intervals.items()
            if now - self._last.get(tier, self.NEVER) >= interval
        ]

    def mark(self, tier: Tier, now: float | None = None) -> None:
        self._last[tier] = now if now is not None else time.monotonic()

    def seconds_until_next(self, now: float | None = None) -> float:
        now = now if now is not None else time.monotonic()
        waits = [
            max(0.0, interval - (now - self._last.get(tier, self.NEVER)))
            for tier, interval in self.intervals.items()
        ]
        return min(waits) if waits else min(self.intervals.values())


def group_by_tier(feeds: list[dict]) -> dict[Tier, list[dict]]:
    grouped: dict[Tier, list[dict]] = {t: [] for t in Tier}
    for feed in feeds:
        grouped[tier_for(feed.get("name", ""), feed.get("category", ""))].append(feed)
    return grouped


def latency_seconds(item: NewsItem, now: datetime | None = None) -> float:
    now = now or datetime.now(timezone.utc)
    published = item.published
    if published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)
    return max(0.0, (now - published).total_seconds())

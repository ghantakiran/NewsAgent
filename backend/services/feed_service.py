"""RSS feed fetching engine and background refresh.

Extracted from app.py lines 1211-1298 and src/newsagent/fetcher.py.
"""

import logging
import sys
import threading
import time
from datetime import datetime, timezone

import feedparser
import httpx

from ..config import ROOT
from .parser_service import parse_entry

sys.path.insert(0, str(ROOT / "src"))

from newsagent.catalysts import fanout as fanout_mod  # noqa: E402
from newsagent.catalysts import sources as sources_mod  # noqa: E402

logger = logging.getLogger(__name__)

# Shared state
_fetch_lock = threading.Lock()
_last_fetch_time: datetime | None = None
_fetch_errors: dict[str, str] = {}


def get_last_fetch_time() -> datetime | None:
    return _last_fetch_time


def get_fetch_errors() -> dict[str, str]:
    return dict(_fetch_errors)


# SEC rejects terse or browser-spoofing agents with a 403; it wants a
# descriptive string identifying the requester.
SEC_USER_AGENT = "NewsAgent/1.0 (open-source market news aggregator; contact via repo)"
DEFAULT_USER_AGENT = "NewsAgent/1.0"


def feed_user_agent(url: str) -> str:
    return SEC_USER_AGENT if "sec.gov" in url else DEFAULT_USER_AGENT


def _items_to_entries(items) -> list[dict]:
    """Adapt NewsItem objects to the entry shape `parse_entry` consumes."""
    return [
        {
            "title": i.title, "link": i.url, "summary": i.summary,
            "published": i.published.isoformat(), "_source": i.source,
        }
        for i in items
    ]


def fetch_feed(feed_url: str, feed_name: str, timeout: float = 20.0) -> list[dict]:
    """Fetch and parse a single source. Returns list of feedparser-like entries."""
    if "finviz" in feed_name.lower():
        try:
            entries = _items_to_entries(sources_mod.fetch_finviz_news(limit=100))
            if entries:
                _fetch_errors.pop(feed_name, None)
            return entries
        except Exception as e:
            _fetch_errors[feed_name] = str(e)[:200]
            logger.warning(f"Error fetching {feed_name}: {str(e)[:100]}")
            return []
    try:
        headers = {
            "User-Agent": feed_user_agent(feed_url),
            "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
        }
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            resp = client.get(feed_url, headers=headers)
            resp.raise_for_status()
        parsed = feedparser.parse(resp.text)
        if parsed.bozo and not parsed.entries:
            raise ValueError(f"Parse error: {parsed.bozo_exception}")
        _fetch_errors.pop(feed_name, None)
        return parsed.entries
    except Exception as e:
        _fetch_errors[feed_name] = str(e)[:200]
        logger.warning(f"Error fetching {feed_name}: {str(e)[:100]}")
        return []


def fetch_all_feeds(feeds: list[dict], insert_fn, insert_ud_fn) -> int:
    """Fetch all enabled feeds and store articles.

    Args:
        feeds: List of feed dicts with keys: name, url, category, enabled
        insert_fn: Callable(article_dict) -> bool (True if new)
        insert_ud_fn: Callable(ud_dict) -> None

    Returns:
        Count of new articles inserted.
    """
    global _last_fetch_time
    from .ud_service import parse_upgrade_downgrade

    with _fetch_lock:
        new_count = 0
        for feed in feeds:
            if not feed.get("enabled", True):
                continue

            feed_name = feed["name"]
            feed_url = feed["url"]
            feed_category = feed.get("category", "general")

            entries = fetch_feed(feed_url, feed_name)
            for entry in entries:
                try:
                    article = parse_entry(entry, entry.get("_source") or feed_name, feed_category)
                    is_new = insert_fn(article)
                    if is_new:
                        new_count += 1
                        # Parse U/D from articles categorized as upgrade/downgrade
                        if article["category"] in ("upgrade", "downgrade") or feed_category == "upgrades_downgrades":
                            ud = parse_upgrade_downgrade(
                                article["title"], article["summary"],
                                article["tickers"], article["published"],
                                article["url"], article["source"],
                            )
                            if ud and ud["ticker"] != "N/A":
                                insert_ud_fn(ud)
                except Exception as e:
                    logger.warning(f"Parse error from {feed_name}: {e}")

        _last_fetch_time = datetime.now(timezone.utc)
        return new_count


class FeedRefresher:
    """Background thread that periodically refreshes feeds."""

    def __init__(self, feeds: list[dict], interval: int = 15,
                 insert_fn=None, insert_ud_fn=None, catalyst_fn=None):
        self.feeds = feeds
        self.interval = interval
        self._running = False
        self._insert_fn = insert_fn
        self._insert_ud_fn = insert_ud_fn
        self._catalyst_fn = catalyst_fn
        self._scheduler = fanout_mod.TieredScheduler()

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        t = threading.Thread(target=self._run, daemon=True)
        t.start()

    def stop(self) -> None:
        self._running = False

    def _run(self) -> None:
        while self._running:
            try:
                # Wires, filings and the halt tape are polled far more often
                # than general market news, which mostly re-reports them.
                due = self._scheduler.due()
                if due:
                    wanted = set(due)
                    batch = [
                        f for f in self.feeds
                        if fanout_mod.tier_for(f.get("name", ""), f.get("category", "")) in wanted
                    ]
                    new = fetch_all_feeds(batch, self._insert_fn, self._insert_ud_fn) if batch else 0
                    for tier in due:
                        self._scheduler.mark(tier)
                    if new > 0:
                        logger.info(f"Fetched {new} new articles ({'+'.join(t.value for t in due)})")
                self._rescan_catalysts()
            except Exception as e:
                logger.error(f"Refresh error: {e}")
            time.sleep(max(2.0, min(self.interval, self._scheduler.seconds_until_next())))

    def _rescan_catalysts(self) -> None:
        """Re-rank catalysts every cycle — recency decays even on a quiet feed."""
        if self._catalyst_fn is None:
            return
        try:
            new, _ = self._catalyst_fn()
            if new:
                logger.info(f"Detected {new} new catalysts")
        except Exception as e:
            logger.warning(f"Catalyst refresh failed: {e}")

    def update_feeds(self, feeds: list[dict]) -> None:
        self.feeds = feeds

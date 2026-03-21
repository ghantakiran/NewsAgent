"""RSS feed fetching engine."""

import logging
import threading
import time
from datetime import datetime, timezone

import feedparser
import httpx

from .database import get_connection, init_db, insert_article, insert_upgrade_downgrade
from .models import Feed
from .parser import parse_entry, parse_upgrade_downgrade

logger = logging.getLogger(__name__)

# Shared state
_fetch_lock = threading.Lock()
_last_fetch_time: datetime | None = None
_fetch_errors: dict[str, str] = {}


def get_last_fetch_time() -> datetime | None:
    return _last_fetch_time


def get_fetch_errors() -> dict[str, str]:
    return dict(_fetch_errors)


def fetch_feed(feed: Feed, timeout: float = 15.0) -> list[dict]:
    """Fetch and parse a single RSS feed. Returns list of feedparser entries."""
    try:
        headers = {
            "User-Agent": "NewsAgent/1.0 (Stock Market News Aggregator)",
            "Accept": "application/rss+xml, application/xml, text/xml, */*",
        }
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            response = client.get(feed.url, headers=headers)
            response.raise_for_status()

        parsed = feedparser.parse(response.text)
        if parsed.bozo and not parsed.entries:
            raise ValueError(f"Feed parse error: {parsed.bozo_exception}")

        _fetch_errors.pop(feed.name, None)
        return parsed.entries

    except Exception as e:
        error_msg = str(e)[:200]
        _fetch_errors[feed.name] = error_msg
        logger.warning(f"Error fetching {feed.name}: {error_msg}")
        return []


def fetch_all_feeds(feeds: list[Feed]) -> int:
    """Fetch all enabled feeds and store articles. Returns count of new articles."""
    global _last_fetch_time

    with _fetch_lock:
        conn = get_connection()
        init_db(conn)
        new_count = 0

        for feed in feeds:
            if not feed.enabled:
                continue

            entries = fetch_feed(feed)
            for entry in entries:
                try:
                    article = parse_entry(entry, feed)
                    inserted = insert_article(conn, article)
                    if inserted:
                        new_count += 1

                    # Check for upgrade/downgrade
                    if article.category.value in ("upgrade", "downgrade"):
                        ud = parse_upgrade_downgrade(article)
                        if ud:
                            insert_upgrade_downgrade(conn, ud)

                except Exception as e:
                    logger.warning(f"Error parsing entry from {feed.name}: {e}")

            feed.last_fetched = datetime.now(timezone.utc)

        conn.close()
        _last_fetch_time = datetime.now(timezone.utc)
        return new_count


class FeedRefresher:
    """Background thread that periodically refreshes feeds."""

    def __init__(self, feeds: list[Feed], interval: int = 30):
        self.feeds = feeds
        self.interval = interval
        self._running = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False

    def _run(self) -> None:
        while self._running:
            try:
                new = fetch_all_feeds(self.feeds)
                if new > 0:
                    logger.info(f"Fetched {new} new articles")
            except Exception as e:
                logger.error(f"Feed refresh error: {e}")
            time.sleep(self.interval)

    def update_feeds(self, feeds: list[Feed]) -> None:
        self.feeds = feeds

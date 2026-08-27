"""News source adapters — RSS plus the HTML aggregators that have no feed.

Finviz has no RSS but is the best free curation layer there is: its news table
links straight to the original publisher (WSJ, Reuters, Barron's), and its
per-ticker page is a ready-made "everything about this symbol" view. Both are
parsed here into the same item shape the RSS path produces, so the catalyst
engine cannot tell where an article came from.

Attribution comes from the *link domain*, not from Finviz — a Reuters story
surfaced by Finviz scores as Reuters, which is what `source_weight` expects.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import feedparser
import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger("newsagent.catalysts.sources")

BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
FEED_ACCEPT = "application/rss+xml, application/atom+xml, application/xml, text/xml, */*"
REQUEST_TIMEOUT = 20.0

FINVIZ_NEWS_URL = "https://finviz.com/news.ashx"
FINVIZ_QUOTE_URL = "https://finviz.com/quote.ashx?t={ticker}"
# Finviz prints wall-clock times with no zone; the site runs on US market time.
MARKET_TZ = ZoneInfo("America/New_York")

# Domain -> display name, so scoring sees "Reuters" rather than "reuters.com".
DOMAIN_SOURCES = {
    "reuters.com": "Reuters", "wsj.com": "Wall Street Journal",
    "bloomberg.com": "Bloomberg", "cnbc.com": "CNBC",
    "marketwatch.com": "MarketWatch", "barrons.com": "Barron's",
    "ft.com": "Financial Times", "finance.yahoo.com": "Yahoo Finance",
    "yahoo.com": "Yahoo Finance", "seekingalpha.com": "Seeking Alpha",
    "benzinga.com": "Benzinga", "investors.com": "Investor's Business Daily",
    "businesswire.com": "Business Wire", "prnewswire.com": "PR Newswire",
    "globenewswire.com": "GlobeNewswire", "accesswire.com": "ACCESSWIRE",
    "stocktitan.net": "StockTitan", "sec.gov": "SEC",
    "fool.com": "Motley Fool", "zacks.com": "Zacks",
    "investing.com": "Investing.com", "nasdaq.com": "Nasdaq",
    "apnews.com": "Associated Press", "axios.com": "Axios",
    "theinformation.com": "The Information", "semafor.com": "Semafor",
    "stocktwits.com": "Stocktwits", "gurufocus.com": "GuruFocus",
    "finviz.com": "Finviz",
}


def source_for_url(url: str, fallback: str = "") -> str:
    """Publisher name from a link, falling back to a cleaned-up host."""
    try:
        host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    except ValueError:
        return fallback
    if not host:
        return fallback
    if host in DOMAIN_SOURCES:
        return DOMAIN_SOURCES[host]
    for domain, name in DOMAIN_SOURCES.items():
        if host.endswith("." + domain):
            return name
    return host or fallback


@dataclass
class NewsItem:
    title: str
    url: str
    source: str
    published: datetime
    summary: str = ""
    tickers: list[str] = field(default_factory=list)
    id: str = ""
    # The symbol whose page produced this item. Only a hint: a per-ticker page
    # also carries peer and sector stories (SRPT's page lists Moderna and
    # Regenxbio), so the engine resolves the real subject from the headline and
    # falls back to the hint only when it cannot.
    ticker_hint: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            basis = self.url or f"{self.source}|{self.title}"
            self.id = hashlib.md5(basis.encode()).hexdigest()

    def as_dict(self) -> dict:
        return {
            "id": self.id, "title": self.title, "url": self.url,
            "source": self.source, "summary": self.summary,
            "published": self.published.isoformat(),
            "ticker_hint": self.ticker_hint,
        }


def make_client(timeout: float = REQUEST_TIMEOUT) -> httpx.Client:
    return httpx.Client(
        timeout=timeout, follow_redirects=True, headers={"User-Agent": BROWSER_UA}
    )


# ── Finviz time parsing ──────────────────────────────────────────────

_FINVIZ_DATETIME_RE = re.compile(r"^([A-Z][a-z]{2}-\d{2}-\d{2})?\s*(\d{1,2}:\d{2}\s?[AP]M)$")


def parse_finviz_time(raw: str, last_date: datetime | None, now: datetime | None = None) -> tuple[datetime, datetime]:
    """Parse a Finviz timestamp into UTC, carrying the date down the table.

    Finviz prints the date only on the first row of each day ("Aug-26-26 11:13AM")
    and bare times ("10:18AM") for the rest, so the caller threads `last_date`
    through the rows. Returns (utc_timestamp, date_to_carry_forward).
    """
    now = now or datetime.now(timezone.utc)
    text = " ".join((raw or "").split())
    text = re.sub(r"^Today\s+", "", text, flags=re.IGNORECASE)

    m = _FINVIZ_DATETIME_RE.match(text)
    if not m:
        return now, last_date
    date_part, time_part = m.group(1), m.group(2).replace(" ", "")

    if date_part:
        try:
            # Deliberately naive: Finviz prints wall-clock market time with no
            # zone, and MARKET_TZ is attached once date and time are combined.
            day = datetime.strptime(date_part, "%b-%d-%y")  # noqa: DTZ007
        except ValueError:
            return now, last_date
    elif last_date is not None:
        day = last_date
    else:
        day = now.astimezone(MARKET_TZ)

    try:
        clock = datetime.strptime(time_part, "%I:%M%p")  # noqa: DTZ007
    except ValueError:
        return now, last_date

    local = datetime(day.year, day.month, day.day, clock.hour, clock.minute, tzinfo=MARKET_TZ)
    # A bare time that lands in the future belongs to the previous day.
    if local > now.astimezone(MARKET_TZ) + timedelta(minutes=5) and not date_part:
        local -= timedelta(days=1)
    return local.astimezone(timezone.utc), local


# ── Finviz adapters ──────────────────────────────────────────────────

def fetch_finviz_news(client: httpx.Client | None = None, limit: int = 100) -> list[NewsItem]:
    """Finviz's front-page news table (the News column, not Blogs)."""
    owns = client is None
    client = client or make_client()
    try:
        resp = client.get(FINVIZ_NEWS_URL)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
    except Exception as exc:
        logger.warning("finviz news fetch failed: %s", exc)
        return []
    finally:
        if owns:
            client.close()

    # Two identical tables: News first, Blogs second. Blogs are opinion columns.
    tables = soup.select("table.styled-table-new")
    if not tables:
        return []

    items: list[NewsItem] = []
    carry: datetime | None = None
    for row in tables[0].select("tr.news_table-row")[:limit]:
        link = row.select_one("a.nn-tab-link") or row.select_one("a[href^=http]")
        if link is None:
            continue
        title = link.get_text(strip=True)
        url = link.get("href", "")
        if not title or not url.startswith("http"):
            continue
        cells = row.select("td")
        stamp = cells[1].get_text(strip=True) if len(cells) > 1 else ""
        published, carry = parse_finviz_time(stamp, carry)
        items.append(NewsItem(
            title=title, url=url, source=source_for_url(url, "Finviz"), published=published
        ))
    return items


def fetch_finviz_ticker(ticker: str, client: httpx.Client | None = None, limit: int = 25) -> list[NewsItem]:
    """Everything Finviz has filed under one symbol, newest first."""
    owns = client is None
    client = client or make_client()
    try:
        resp = client.get(FINVIZ_QUOTE_URL.format(ticker=ticker.upper()))
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
    except Exception as exc:
        logger.debug("finviz ticker fetch failed for %s: %s", ticker, exc)
        return []
    finally:
        if owns:
            client.close()

    table = soup.select_one("#news-table")
    if table is None:
        return []

    items: list[NewsItem] = []
    carry: datetime | None = None
    for row in table.select("tr"):
        cells = row.select("td")
        if not cells:
            continue
        published, carry = parse_finviz_time(cells[0].get_text(strip=True), carry)
        link = row.select_one("a[href^=http]")
        if link is None:
            continue
        title = link.get_text(strip=True)
        url = link.get("href", "")
        if not title or not url:
            continue
        provider = row.select_one("span")
        source = (provider.get_text(strip=True).strip("()") if provider else "") or source_for_url(url, "Finviz")
        items.append(NewsItem(
            title=title, url=url, source=source, published=published,
            ticker_hint=ticker.upper(),
        ))
        if len(items) >= limit:
            break
    return items


# ── RSS adapter ──────────────────────────────────────────────────────

def _entry_published(entry: dict) -> datetime:
    for key in ("published_parsed", "updated_parsed"):
        parsed = entry.get(key)
        if parsed:
            try:
                return datetime(*parsed[:6], tzinfo=timezone.utc)
            except (TypeError, ValueError):
                continue
    return datetime.now(timezone.utc)


def fetch_rss(
    url: str,
    source: str,
    client: httpx.Client | None = None,
    limit: int = 40,
    ticker_hint: str = "",
) -> list[NewsItem]:
    owns = client is None
    client = client or make_client()
    try:
        resp = client.get(url, headers={"Accept": FEED_ACCEPT})
        resp.raise_for_status()
        parsed = feedparser.parse(resp.text)
    except Exception as exc:
        logger.debug("rss fetch failed for %s: %s", source, exc)
        return []
    finally:
        if owns:
            client.close()

    items = []
    for entry in parsed.entries[:limit]:
        title = (entry.get("title") or "").strip()
        if not title:
            continue
        raw_summary = entry.get("summary") or entry.get("description") or ""
        summary = BeautifulSoup(raw_summary, "html.parser").get_text(" ", strip=True)[:500]
        items.append(NewsItem(
            title=title, url=entry.get("link", ""), source=source,
            published=_entry_published(entry), summary=summary,
            ticker_hint=ticker_hint,
        ))
    return items

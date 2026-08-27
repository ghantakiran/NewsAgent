"""Earnings result parsing and extraction.

Extracted from app.py lines 2487-2584.
"""

import re
from dataclasses import dataclass
from datetime import datetime

from .parser_service import extract_ticker_from_name

_EPS_PATTERN = re.compile(
    r'(?:(?:Non-GAAP|GAAP)?\s*EPS\s+(?:of\s+)?\$?([-]?[\d.]+))'
    r'|(?:EPS:\s*\$?([-]?[\d.]+))',
    re.IGNORECASE,
)
_REVENUE_PATTERN = re.compile(
    r'revenue\s+(?:of\s+)?\$?([\d,.]+)\s*(B|M|K)?',
    re.IGNORECASE,
)


def parse_earnings_from_article(title: str, summary: str, tickers: list[str],
                                url: str, source: str, published: datetime,
                                category: str) -> dict | None:
    """Extract earnings data from an earnings-categorized article.

    Returns a dict with earnings fields or None.
    """
    if category != "earnings":
        return None

    text = title + " " + summary

    # Extract ticker
    ticker = tickers[0] if tickers else ""
    if not ticker:
        ticker = extract_ticker_from_name(title) or ""

    # Extract EPS
    eps = ""
    m = _EPS_PATTERN.search(text)
    if m:
        val = m.group(1) or m.group(2)
        if val:
            eps = f"${val}"

    # Extract revenue
    revenue = ""
    m = _REVENUE_PATTERN.search(text)
    if m:
        val = m.group(1)
        suffix = (m.group(2) or "").upper()
        revenue = f"${val}{suffix}"

    # Detect beat/miss
    beat_miss = ""
    text_lower = text.lower()
    if any(w in text_lower for w in ["beats", "beat", "topped", "exceeded"]):
        beat_miss = "beat"
    elif any(w in text_lower for w in ["misses", "miss", "missed", "fell short"]):
        beat_miss = "miss"
    elif "in-line" in text_lower or "in line" in text_lower:
        beat_miss = "inline"

    if eps or revenue or beat_miss or ticker:
        return {
            "ticker": ticker,
            "title": title,
            "url": url,
            "source": source,
            "published": published,
            "eps": eps,
            "revenue": revenue,
            "beat_miss": beat_miss,
        }
    return None


def get_earnings_by_ticker(results: list[dict]) -> dict[str, list[dict]]:
    """Group earnings results by ticker."""
    by_ticker: dict[str, list[dict]] = {}
    for er in results:
        t = er.get("ticker") or "N/A"
        if t not in by_ticker:
            by_ticker[t] = []
        by_ticker[t].append(er)
    return by_ticker

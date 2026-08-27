"""Article filtering, deduplication, noise detection, and breaking news.

Extracted from app.py lines 2321-2619.
"""

import re

from ..models.schemas import Category

# ──────────────────────────────────────────────────────────────
#  Noise filter patterns (from app.py lines 2324-2372)
# ──────────────────────────────────────────────────────────────

_NOISE_PATTERNS = [
    # Personal finance / lifestyle
    r"(?i)\b(?:husband|wife|divorce|wedding|marriage|dating|romance)\b",
    r"(?i)\b(?:horoscope|zodiac|astrology|celebrity gossip)\b",
    r"(?i)\b(?:recipe|cookbook|diet plan|weight loss tips)\b",
    r"(?i)\b(?:sports score|nfl draft|nba playoff|world cup|super bowl)\b",
    # Form 4 / Form 144 SEC filings
    r"(?i)^form\s+(?:4|144)\s",
    # Minor insider transactions
    r"(?i)\bsells?\s+\$[\d,.]+\s*(?:k|m|million|thousand)?\s+(?:in\s+)?(?:shares|stock|class\s+[a-z])\b",
    r"(?i)\b(?:director|officer|counsel|cpo|cfo|coo|cto|ceo|svp|evp|vp|president)\b.*\bsells?\b.*\b(?:shares?|stock|million)\b",
    # Foreign market predictions
    r"(?i)^(?:malaysia|japan|australia|india|hong kong|singapore|south korea|korea|taiwan|europe|china)\s+shares?\s+(?:tipped|may|set|expected|poised)\b",
    # Clickbait
    r"(?i)^(?:ask an advisor|it.s complicated|dear moneyist)\b",
    # Generic technical signals
    r"(?i)^notable\s+(?:two hundred|200|fifty|50)\s+day\s+moving\s+average",
    r"(?i)^(?:oversold conditions|rsi alert|relative strength alert)\b",
    r"(?i)\b(?:becomes oversold|enters oversold|now oversold)\b",
    r"(?i)^(?:\w+\s+)?breaks?\s+(?:below|above)\s+\d+-day\s+moving\s+average",
    # Board/director noise
    r"(?i)\b(?:resigns?|resignation)\b.*\b(?:board|director)\b",
    r"(?i)\b(?:replaces?|retains?)\b.*\b(?:independent\s+)?auditor\b",
    # Generic foreign market summaries
    r"(?i)^(?:south\s+)?korea\s+shares\b",
    # Insider buys/sells of minor amounts
    r"(?i)\bbuys?\b.*\bshares?\s+worth\s+\$[\d,.]+[kmKM]?\b",
    r"(?i)\bsells?\s+\$[\d,.]+(?:k|m)?\s+in\s+(?:shares|stock)\b",
    r"(?i)\bsells?\s+\$[\d,.]+\s+(?:million|thousand)\s+in\s+(?:shares|stock)\b",
    r"(?i)\bsells?\b.*\bafter\s+option\s+exercise\b",
    # Trial/lawsuit noise
    r"(?i)\b(?:trial|lawsuit|deposition|subpoena)\b.*\b(?:nears?\s+end|begins?|filed)\b",
    # Clickbait stock movement articles
    r"(?i)^why\s+\w+\s+stock\s+(?:zoomed|soared|tanked|plunged|crashed|spiked|surged)\b",
    # Generic market filler
    r"(?i)^stock\s+market\s+today[,:]",
]
_NOISE_RES = [re.compile(p) for p in _NOISE_PATTERNS]

_SOFTBLOCK_PATTERNS = [
    r"(?i)\bappoints?\b.*\b(?:as\s+)?(?:president|director|board|chairman|advisor)\b",
    r"(?i)\b(?:names|hires|taps)\b.*\b(?:new\s+)?(?:ceo|cfo|coo|cto|president|director)\b",
]
_SOFTBLOCK_RES = [re.compile(p) for p in _SOFTBLOCK_PATTERNS]

# Breaking news categories — high-impact for stock trading
BREAKING_CATEGORIES = {"earnings", "upgrade", "downgrade", "macro", "m&a", "fda", "ipo"}

# Short source name mapping
SOURCE_SHORT = {
    "Investing.com News": "Investing",
    "MarketWatch Top Stories": "MarketWatch",
    "CNBC Top News": "CNBC",
    "Benzinga News": "Benzinga",
    "Nasdaq Original Content": "Nasdaq",
    "Yahoo Finance News": "Yahoo",
    "Seeking Alpha": "SeekingAlpha",
    "Seeking Alpha News": "SeekingAlpha",
    "Google News - Analyst Upgrades": "GNews",
    "Google News - Stock Upgrades Downgrades": "GNews",
}


def is_noise(title: str, category: str = "general", has_ticker: bool = False) -> bool:
    """Return True if this article should be filtered from the Live Feed."""
    if any(p.search(title) for p in _NOISE_RES):
        return True
    if category == "general" and not has_ticker:
        if any(p.search(title) for p in _SOFTBLOCK_RES):
            return True
    return False


def deduplicate_articles(articles: list[dict], apply_noise_filter: bool = True) -> list[dict]:
    """Deduplicate articles by title and optionally filter noise."""
    seen_titles = set()
    deduped = []
    for a in articles:
        key = a["title"].strip().lower()[:80]
        if key in seen_titles:
            continue
        if apply_noise_filter and is_noise(a["title"], a.get("category", "general"), bool(a.get("tickers"))):
            continue
        seen_titles.add(key)
        deduped.append(a)
    return deduped


def filter_breaking(articles: list[dict], limit: int = 30) -> list[dict]:
    """Filter articles for breaking news feed — prioritize high-impact categories."""
    breaking = [a for a in articles if a.get("category") in BREAKING_CATEGORIES]
    general_recent = [a for a in articles if a.get("category") not in BREAKING_CATEGORIES]
    combined = breaking + general_recent
    return deduplicate_articles(combined)[:limit]


def short_source(name: str) -> str:
    """Get abbreviated source name for display."""
    if name in SOURCE_SHORT:
        return SOURCE_SHORT[name]
    nl = name.lower()
    if "seeking" in nl:
        return "SeekingAlpha"
    if "yahoo" in nl:
        return "Yahoo"
    if "nasdaq" in nl:
        return "Nasdaq"
    return name[:14]


def relative_time_str(published_dt, now_dt) -> str:
    """Return a human-readable relative time string like '2m ago'."""
    try:
        diff = now_dt - published_dt
        secs = int(diff.total_seconds())
        if secs < 0:
            return "just now"
        if secs < 60:
            return f"{secs}s ago"
        mins = secs // 60
        if mins < 60:
            return f"{mins}m ago"
        hours = mins // 60
        if hours < 24:
            return f"{hours}h ago"
        days = hours // 24
        return f"{days}d ago"
    except Exception:
        return ""

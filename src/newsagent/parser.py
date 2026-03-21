"""Article parsing, ticker extraction, and categorization."""

import hashlib
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from bs4 import BeautifulSoup

from .models import Article, Category, UpgradeDowngrade

# Common English words that look like tickers but aren't
TICKER_EXCLUSIONS = {
    "A", "I", "AM", "PM", "AN", "AS", "AT", "BE", "BY", "DO", "GO", "HE",
    "IF", "IN", "IS", "IT", "ME", "MY", "NO", "OF", "OK", "ON", "OR", "SO",
    "TO", "UP", "US", "WE", "CEO", "CFO", "COO", "CTO", "FDA", "SEC", "FED",
    "GDP", "IPO", "ETF", "NYSE", "ALL", "ARE", "BUT", "CAN", "FOR", "HAS",
    "HAD", "HIS", "HOW", "ITS", "MAY", "NEW", "NOT", "NOW", "OLD", "OUR",
    "OUT", "OWN", "SAY", "SHE", "THE", "TOO", "TWO", "WAR", "WAY", "WHO",
    "WHY", "BIG", "DAY", "TOP", "LOW", "HIGH", "ALSO", "JUST", "OVER",
    "THAN", "THEM", "VERY", "WHEN", "WITH", "FROM", "HERE", "INTO", "LAST",
    "LONG", "MADE", "MANY", "MORE", "MOST", "MUCH", "MUST", "NAME", "ONLY",
    "PART", "SAID", "SAME", "SOME", "SUCH", "TELL", "THAT", "THIS", "WHAT",
    "WILL", "YEAR", "YOUR", "AFTER", "COULD", "EVERY", "FIRST", "ABOUT",
    "BEEN", "CALL", "CAME", "COME", "EACH", "FIND", "FREE", "GOOD", "HAVE",
    "HELP", "HOLD", "KEEP", "KNOW", "LIKE", "LIVE", "LOOK", "MAKE", "NEAR",
    "NEXT", "OPEN", "PLAN", "REAL", "RISE", "SEEN", "SHOW", "TAKE", "TURN",
    "WANT", "WELL", "WORK", "EVEN", "BACK", "DOWN", "FULL", "GIVE", "GOES",
    "HALF", "LATE", "LESS", "LOSS", "MOVE", "NEED", "ONCE", "RATE", "REST",
    "SELL", "SIDE", "SIGN", "STILL", "SURE", "TALK", "THEM", "THEN",
    "USED", "WEEK", "BEST", "BOTH", "DEAL", "DOES", "DONE", "DREW", "EVER",
    "FACT", "GETS", "GETS", "GREW", "GROW", "HOPE", "HUGE", "IDEA", "LEFT",
    "LINE", "LINK", "LIST", "LOST", "MAIN", "MARK", "MEAN", "MEET", "NOTE",
    "PAST", "PLAY", "PUSH", "READ", "SAYS", "SENT", "SET", "STEP", "STOP",
    "TEST", "TOLD", "TRUE", "TYPE", "VIEW", "VOTE", "WAIT", "WENT", "WERE",
    "WIDE", "WIN", "WON", "WORD", "ZERO",
    "EST", "PST", "CST", "MST", "UTC", "RSS", "CEO", "USA", "UK",
    "AI", "EV", "TV", "PE", "Q1", "Q2", "Q3", "Q4",
    "GAAP", "EPS", "YOY", "QOQ", "MOM", "ROI", "ROE", "ROA",
    "ETF", "REIT", "SPAC", "ADR", "OTC", "P2P", "B2B", "B2C",
    "API", "CEO", "CFO", "CIO", "CMO", "COO", "CTO", "EVP", "SVP",
    "DMA", "RSI", "MACD", "SMA", "EMA", "ATH", "ATL",
    "FY", "YTD", "QTD", "MTD", "TTM",
    "LLC", "INC", "LTD", "PLC", "SA", "AG", "NV",
    "IPO", "M&A", "P&L", "R&D", "S&P", "NYSE", "AMEX",
    "AM", "PM", "EST", "PST", "CST", "MST", "UTC",
    "GDP", "CPI", "PPI", "PCE", "PMI", "ISM",
}

TICKER_PATTERN = re.compile(r'\b([A-Z]{1,5})\b')

# Category keyword maps
CATEGORY_KEYWORDS = {
    Category.EARNINGS: [
        "earnings", "eps", "revenue", "quarterly results", "beats estimates",
        "misses estimates", "quarterly report", "fiscal quarter", "guidance",
        "profit", "loss report", "income report",
    ],
    Category.UPGRADE: [
        "upgrade", "upgrades", "raised to buy", "raised to overweight",
        "raised to outperform", "price target raised", "target raised",
    ],
    Category.DOWNGRADE: [
        "downgrade", "downgrades", "cut to sell", "cut to underweight",
        "cut to underperform", "price target lowered", "target lowered",
    ],
    Category.MACRO: [
        "fed ", "federal reserve", "interest rate", "inflation", "cpi",
        "ppi", "gdp", "jobs report", "unemployment", "fomc", "powell",
        "treasury yield", "economic data", "nonfarm", "rate cut",
        "rate hike", "monetary policy",
    ],
    Category.FDA: [
        "fda", "drug approval", "clinical trial", "phase 3", "phase 2",
        "pdufa", "nda", "biologic", "therapeutic",
    ],
    Category.MA: [
        "acquire", "acquisition", "merger", "buyout", "takeover",
        "deal to buy", "bid for", "merge with",
    ],
    Category.IPO: [
        "ipo", "initial public offering", "direct listing", "spac",
        "goes public", "debut",
    ],
    Category.INSIDER: [
        "insider", "insider buying", "insider selling", "form 4",
        "officer buys", "director sells",
    ],
    Category.DIVIDEND: [
        "dividend", "ex-dividend", "declares dividend", "special dividend",
        "dividend increase", "dividend cut",
    ],
    Category.FILING: [
        "8-k", "10-k", "10-q", "sec filing", "13f", "13d",
        "proxy statement",
    ],
    Category.CRYPTO: [
        "bitcoin", "ethereum", "cryptocurrency", "crypto currency",
        "blockchain", "defi", "altcoin", "stablecoin", "cryptomarket",
    ],
}


def make_article_id(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()


def extract_tickers(text: str) -> list[str]:
    """Extract stock ticker symbols from text."""
    matches = TICKER_PATTERN.findall(text)
    tickers = []
    seen = set()
    for m in matches:
        if m not in TICKER_EXCLUSIONS and m not in seen:
            tickers.append(m)
            seen.add(m)
    return tickers[:10]  # cap at 10 tickers per article


def categorize(title: str, summary: str, feed_category: str) -> Category:
    """Categorize an article based on title and summary content."""
    text = (title + " " + summary).lower()

    # Check feed-level category first
    if feed_category == "upgrades_downgrades":
        if any(kw in text for kw in CATEGORY_KEYWORDS[Category.DOWNGRADE]):
            return Category.DOWNGRADE
        return Category.UPGRADE
    if feed_category == "fda":
        return Category.FDA
    if feed_category == "filings":
        return Category.FILING

    # Keyword-based detection
    for cat, keywords in CATEGORY_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            return cat

    return Category.GENERAL


def parse_published_date(entry: dict) -> datetime:
    """Parse publication date from RSS entry."""
    for date_field in ("published", "updated", "created"):
        raw = entry.get(date_field, "")
        if raw:
            try:
                return parsedate_to_datetime(raw)
            except (ValueError, TypeError):
                pass
            # Try ISO format
            try:
                return datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                pass
    return datetime.now(timezone.utc)


def clean_html(html: str) -> str:
    """Strip HTML tags and return plain text."""
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    return soup.get_text(separator=" ", strip=True)[:500]


def parse_entry(entry: dict, feed: "Feed") -> Article:
    """Parse a feedparser entry into an Article."""
    title = entry.get("title", "No title")
    url = entry.get("link", "")
    summary_raw = entry.get("summary", entry.get("description", ""))
    summary = clean_html(summary_raw)

    published = parse_published_date(entry)
    category = categorize(title, summary, feed.category)
    tickers = extract_tickers(title + " " + summary)

    return Article(
        id=make_article_id(url),
        title=title,
        url=url,
        source=feed.name,
        published=published,
        category=category,
        tickers=tickers,
        summary=summary,
    )


def parse_upgrade_downgrade(article: Article) -> UpgradeDowngrade | None:
    """Try to extract upgrade/downgrade details from an article."""
    text = article.title + " " + article.summary
    text_lower = text.lower()

    if "upgrade" in text_lower:
        action = "upgrade"
    elif "downgrade" in text_lower:
        action = "downgrade"
    elif "initiated" in text_lower or "initiate" in text_lower:
        action = "initiated"
    elif "reiterate" in text_lower:
        action = "reiterated"
    elif "target" in text_lower and "price" in text_lower:
        action = "price_target"
    else:
        return None

    ticker = article.tickers[0] if article.tickers else "N/A"

    # Try to extract firm name — common pattern: "Firm upgrades Ticker"
    firm = "Unknown"
    firm_patterns = [
        r'([\w\s]+?)\s+(?:upgrades?|downgrades?|initiates?|reiterates?)',
        r'(?:at|by|from)\s+([\w\s]+?)(?:\s*[,;:\-])',
    ]
    for pattern in firm_patterns:
        m = re.search(pattern, article.title, re.IGNORECASE)
        if m:
            firm = m.group(1).strip()[:50]
            break

    # Try to extract ratings
    old_rating = ""
    new_rating = ""
    rating_pattern = r'from\s+([\w\s]+?)\s+to\s+([\w\s]+?)(?:\s*[,;.\-]|$)'
    m = re.search(rating_pattern, text, re.IGNORECASE)
    if m:
        old_rating = m.group(1).strip()[:30]
        new_rating = m.group(2).strip()[:30]

    # Try to extract price target
    price_target = ""
    pt_pattern = r'(?:price target|pt|target)\s*(?:of|to|at|:)?\s*\$?([\d,.]+)'
    m = re.search(pt_pattern, text, re.IGNORECASE)
    if m:
        price_target = f"${m.group(1)}"

    return UpgradeDowngrade(
        ticker=ticker,
        firm=firm,
        action=action,
        old_rating=old_rating,
        new_rating=new_rating,
        price_target=price_target,
        published=article.published,
        source_url=article.url,
        source=article.source,
    )

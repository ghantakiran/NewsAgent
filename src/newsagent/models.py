"""Data models for NewsAgent."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class Category(str, Enum):
    GENERAL = "general"
    EARNINGS = "earnings"
    UPGRADE = "upgrade"
    DOWNGRADE = "downgrade"
    MACRO = "macro"
    FDA = "fda"
    MA = "m&a"  # mergers & acquisitions
    IPO = "ipo"
    INSIDER = "insider"
    DIVIDEND = "dividend"
    FILING = "filing"
    CRYPTO = "crypto"
    TECH = "tech"


CATEGORY_COLORS = {
    Category.GENERAL: "#9e9e9e",
    Category.EARNINGS: "#ffd700",
    Category.UPGRADE: "#00c853",
    Category.DOWNGRADE: "#ff1744",
    Category.MACRO: "#2979ff",
    Category.FDA: "#aa00ff",
    Category.MA: "#ff9100",
    Category.IPO: "#00e5ff",
    Category.INSIDER: "#ff6d00",
    Category.DIVIDEND: "#76ff03",
    Category.FILING: "#8d6e63",
    Category.CRYPTO: "#f4511e",
    Category.TECH: "#7c4dff",
}


@dataclass
class Article:
    id: str  # hash of url
    title: str
    url: str
    source: str
    published: datetime
    category: Category = Category.GENERAL
    tickers: list[str] = field(default_factory=list)
    summary: str = ""
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class Feed:
    name: str
    url: str
    category: str = "general"
    enabled: bool = True
    last_fetched: datetime | None = None
    error: str | None = None


@dataclass
class UpgradeDowngrade:
    ticker: str
    firm: str
    action: str  # "upgrade", "downgrade", "initiated", "reiterated"
    old_rating: str
    new_rating: str
    price_target: str = ""
    published: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    source_url: str = ""
    source: str = ""

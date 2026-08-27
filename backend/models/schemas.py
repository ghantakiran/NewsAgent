"""Pydantic models for API request/response schemas."""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class Category(str, Enum):
    GENERAL = "general"
    EARNINGS = "earnings"
    UPGRADE = "upgrade"
    DOWNGRADE = "downgrade"
    MACRO = "macro"
    FDA = "fda"
    MA = "m&a"
    IPO = "ipo"
    INSIDER = "insider"
    DIVIDEND = "dividend"
    FILING = "filing"
    CRYPTO = "crypto"
    TECH = "tech"


CATEGORY_COLORS = {
    Category.GENERAL: "#6b7394",
    Category.EARNINGS: "#f5c542",
    Category.UPGRADE: "#00d68f",
    Category.DOWNGRADE: "#ff3b4e",
    Category.MACRO: "#0ea5e9",
    Category.FDA: "#a78bfa",
    Category.MA: "#f97316",
    Category.IPO: "#06b6d4",
    Category.INSIDER: "#fb923c",
    Category.DIVIDEND: "#4ade80",
    Category.FILING: "#94a3b8",
    Category.CRYPTO: "#f59e0b",
    Category.TECH: "#8b5cf6",
}


class ArticleResponse(BaseModel):
    id: str
    title: str
    url: str
    source: str
    published: datetime
    category: Category = Category.GENERAL
    tickers: list[str] = Field(default_factory=list)
    summary: str = ""
    fetched_at: datetime | None = None


class ArticleListResponse(BaseModel):
    articles: list[ArticleResponse]
    total: int
    deduped_count: int


class UpgradeDowngradeResponse(BaseModel):
    ticker: str
    firm: str
    action: str
    old_rating: str
    new_rating: str
    price_target: str = ""
    published: datetime
    source_url: str = ""
    source: str = ""
    grade: str = ""


class UDListResponse(BaseModel):
    upgrades: list[UpgradeDowngradeResponse]
    downgrades: list[UpgradeDowngradeResponse]
    mixed: list[UpgradeDowngradeResponse]
    unresolved: list[UpgradeDowngradeResponse]
    total: int
    grade_counts: dict[str, int]


class EarningsResultResponse(BaseModel):
    ticker: str
    title: str
    url: str
    source: str
    published: datetime
    eps: str = ""
    revenue: str = ""
    beat_miss: str = ""


class EarningsListResponse(BaseModel):
    results: list[EarningsResultResponse]
    total: int
    by_ticker: dict[str, list[EarningsResultResponse]] = Field(default_factory=dict)


class FeedResponse(BaseModel):
    name: str
    url: str
    category: str = "general"
    enabled: bool = True
    last_fetched: datetime | None = None
    error: str | None = None
    is_custom: bool = False


class FeedListResponse(BaseModel):
    feeds: list[FeedResponse]
    errors: dict[str, str] = Field(default_factory=dict)


class CustomFeedCreate(BaseModel):
    name: str
    url: str
    category: str = "general"


class CustomFeedUpdate(BaseModel):
    enabled: bool | None = None
    category: str | None = None


class StatsResponse(BaseModel):
    article_count: int
    active_sources: int
    source_counts: dict[str, int]
    last_fetch_time: datetime | None = None
    fetch_errors: dict[str, str] = Field(default_factory=dict)
    refresh_interval: int


class BreakingResponse(BaseModel):
    articles: list[ArticleResponse]
    count: int


# Auth schemas

class UserRegister(BaseModel):
    email: str
    password: str


class UserLogin(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class TokenRefresh(BaseModel):
    refresh_token: str


class WatchlistUpdate(BaseModel):
    tickers: list[str]


class WatchlistResponse(BaseModel):
    tickers: list[str]


class UserSettingsUpdate(BaseModel):
    timezone: str | None = None
    notification_prefs: dict | None = None


class UserSettingsResponse(BaseModel):
    timezone: str = "America/New_York"
    notification_prefs: dict = Field(default_factory=dict)


# Discord route config schemas

class DiscordRouteUpdate(BaseModel):
    webhook_url: str
    enabled: bool = True


class DiscordRouteResponse(BaseModel):
    category: str
    configured: bool = False
    enabled: bool = False
    disabled: bool = False
    fail_count: int = 0
    masked_url: str = ""
    updated_at: str | None = None


class DiscordRouteListResponse(BaseModel):
    routes: list[DiscordRouteResponse]
    categories: list[str]


class DiscordTestRequest(BaseModel):
    webhook_url: str | None = None


class DiscordTestResponse(BaseModel):
    ok: bool
    message: str


# TradingView inbound alert + coalesced alert-group schemas

class TradingViewAlert(BaseModel):
    """Normalized inbound alert. TradingView's alert message should be JSON with
    (any of) these fields; unknown fields are kept under `extra`. Raw text
    bodies are parsed best-effort in the router before reaching this model."""
    ticker: str = ""
    category: str = "general"
    signal: str = ""        # e.g. "long" / "short" / "breakout"
    timeframe: str = ""     # e.g. "5m" / "1h"
    price: float | None = None
    message: str = ""
    extra: dict = Field(default_factory=dict)

    model_config = {"extra": "allow"}


class AlertGroupResponse(BaseModel):
    group_id: str
    category: str = "general"
    ticker: str = ""
    timeframe: str = ""
    signal: str = ""
    count: int = 1
    first_seen: datetime
    last_seen: datetime
    latest: dict = Field(default_factory=dict)
    history: list[dict] = Field(default_factory=list)


class AlertGroupListResponse(BaseModel):
    groups: list[AlertGroupResponse]
    total: int

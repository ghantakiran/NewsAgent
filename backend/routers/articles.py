"""Article endpoints: live feed, breaking news, by symbol."""

import sqlite3
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query

from ..core.database import get_articles, get_articles_by_ticker, get_all_tickers
from ..core.deps import get_db
from ..models.schemas import ArticleListResponse, ArticleResponse, BreakingResponse
from ..services.article_service import deduplicate_articles, filter_breaking
from ..services.parser_service import extract_ticker_from_name

router = APIRouter(prefix="/api/v1", tags=["articles"])


@router.get("/articles", response_model=ArticleListResponse)
def list_articles(
    category: str | None = Query(None),
    ticker: str | None = Query(None),
    search: str | None = Query(None),
    hours: int = Query(48),
    limit: int = Query(100, le=500),
    filtered: bool = Query(True, description="Apply noise filter"),
    conn: sqlite3.Connection = Depends(get_db),
):
    arts = get_articles(conn, limit=limit, category=category, ticker=ticker, search=search, hours=hours)
    deduped = deduplicate_articles(arts, apply_noise_filter=filtered)
    return ArticleListResponse(
        articles=[ArticleResponse(**a) for a in deduped],
        total=len(arts),
        deduped_count=len(deduped),
    )


@router.get("/articles/breaking", response_model=BreakingResponse)
def breaking_news(
    hours: float = Query(2.0),
    limit: int = Query(30, le=100),
    conn: sqlite3.Connection = Depends(get_db),
):
    cutoff_hours = max(hours, 0.5)
    arts = get_articles(conn, limit=limit * 3, hours=int(cutoff_hours + 1))
    # Filter to actual cutoff window
    cutoff = datetime.now(timezone.utc) - timedelta(hours=cutoff_hours)
    arts = [a for a in arts if (a["published"].replace(tzinfo=timezone.utc) if a["published"].tzinfo is None else a["published"]) >= cutoff]
    breaking = filter_breaking(arts, limit=limit)
    return BreakingResponse(
        articles=[ArticleResponse(**a) for a in breaking],
        count=len(breaking),
    )


@router.get("/articles/by-symbol")
def articles_by_symbol(
    symbols: str | None = Query(None, description="Comma-separated ticker symbols"),
    search: str | None = Query(None),
    limit_per: int = Query(10, le=50),
    conn: sqlite3.Connection = Depends(get_db),
):
    all_tickers = get_all_tickers(conn)

    if symbols:
        requested = [s.strip().upper() for s in symbols.split(",")]
        matching = [t for t in all_tickers if t in requested]
    elif search:
        matching = [t for t in all_tickers if search.upper() in t]
        if not matching:
            mapped = extract_ticker_from_name(search)
            if mapped:
                matching = [mapped]
    else:
        matching = all_tickers[:30]

    by_ticker = get_articles_by_ticker(conn, limit_per_ticker=limit_per)
    result = {}
    for ticker in matching:
        arts = by_ticker.get(ticker, [])
        if not arts:
            arts = get_articles(conn, limit=limit_per, ticker=ticker)
        result[ticker] = [ArticleResponse(**a) for a in arts]

    return {"symbols": result, "total_symbols": len(matching)}


@router.get("/articles/tickers")
def list_tickers(conn: sqlite3.Connection = Depends(get_db)):
    return {"tickers": get_all_tickers(conn)}

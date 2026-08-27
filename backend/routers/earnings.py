"""Earnings endpoints."""

import sqlite3

from fastapi import APIRouter, Depends, Query

from ..core.database import get_articles
from ..core.deps import get_db
from ..models.schemas import EarningsListResponse, EarningsResultResponse
from ..services.earnings_service import get_earnings_by_ticker, parse_earnings_from_article

router = APIRouter(prefix="/api/v1", tags=["earnings"])


@router.get("/earnings", response_model=EarningsListResponse)
def list_earnings(
    hours: int = Query(48),
    filter: str | None = Query(None, description="beats, misses, has_eps"),
    search: str | None = Query(None),
    conn: sqlite3.Connection = Depends(get_db),
):
    arts = get_articles(conn, limit=500, category="earnings", hours=hours)

    results = []
    seen = set()
    for a in arts:
        er = parse_earnings_from_article(
            a["title"], a["summary"], a["tickers"],
            a["url"], a["source"], a["published"], a["category"],
        )
        if er:
            key = er["title"].strip().lower()[:60]
            if key not in seen:
                seen.add(key)
                results.append(er)

    # Apply filters
    if search:
        q = search.strip().upper()
        results = [r for r in results if q in r["ticker"] or q.lower() in r["title"].lower()]
    if filter == "beats":
        results = [r for r in results if r["beat_miss"] == "beat"]
    elif filter == "misses":
        results = [r for r in results if r["beat_miss"] == "miss"]
    elif filter == "has_eps":
        results = [r for r in results if r["eps"]]

    by_ticker = get_earnings_by_ticker(results)

    return EarningsListResponse(
        results=[EarningsResultResponse(**r) for r in results],
        total=len(results),
        by_ticker={
            t: [EarningsResultResponse(**r) for r in ers]
            for t, ers in by_ticker.items()
            if t and t != "N/A"
        },
    )

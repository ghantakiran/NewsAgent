"""Stats endpoint."""

import sqlite3

from fastapi import APIRouter, Depends

from ..core.database import get_article_count, get_source_counts
from ..core.deps import get_db
from ..models.schemas import StatsResponse
from ..services.feed_service import get_fetch_errors, get_last_fetch_time

router = APIRouter(prefix="/api/v1", tags=["stats"])


@router.get("/stats", response_model=StatsResponse)
def get_stats(conn: sqlite3.Connection = Depends(get_db)):
    count = get_article_count(conn)
    sources = get_source_counts(conn)
    lft = get_last_fetch_time()
    errors = get_fetch_errors()

    return StatsResponse(
        article_count=count,
        active_sources=len(sources),
        source_counts=sources,
        last_fetch_time=lft,
        fetch_errors=errors,
        refresh_interval=15,
    )

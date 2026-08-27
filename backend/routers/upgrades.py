"""Upgrade/Downgrade ratings endpoints."""

import sqlite3

from fastapi import APIRouter, Depends, Query

from ..core.database import get_upgrades_downgrades, reprocess_upgrades_downgrades
from ..core.deps import get_db
from ..models.schemas import UDListResponse, UpgradeDowngradeResponse
from ..services.ud_service import grade_ud

router = APIRouter(prefix="/api/v1", tags=["upgrades-downgrades"])


@router.get("/upgrades-downgrades", response_model=UDListResponse)
def list_upgrades_downgrades(
    ticker: str | None = Query(None),
    search: str | None = Query(None),
    hours: int = Query(48),
    limit: int = Query(300, le=1000),
    conn: sqlite3.Connection = Depends(get_db),
):
    uds = get_upgrades_downgrades(conn, limit=limit, ticker=ticker, search=search, hours=hours)

    # Grade each entry
    for ud in uds:
        ud["grade"] = grade_ud(ud["ticker"], ud["firm"], ud["new_rating"], ud["price_target"], ud["action"])

    # Split into categories
    upgrades = [ud for ud in uds if ud["action"] in ("upgrade", "initiated", "raises_pt")]
    downgrades = [ud for ud in uds if ud["action"] in ("downgrade", "lowers_pt")]
    mixed_all = [ud for ud in uds if ud["action"] not in ("upgrade", "initiated", "raises_pt", "downgrade", "lowers_pt")]
    mixed_detailed = [ud for ud in mixed_all if ud["firm"] or ud["new_rating"] or ud["price_target"]]
    mixed_bare = [ud for ud in mixed_all if not ud["firm"] and not ud["new_rating"] and not ud["price_target"]]

    # Grade counts
    grade_counts: dict[str, int] = {}
    for ud in uds:
        g = ud["grade"]
        grade_counts[g] = grade_counts.get(g, 0) + 1

    return UDListResponse(
        upgrades=[UpgradeDowngradeResponse(**ud) for ud in upgrades],
        downgrades=[UpgradeDowngradeResponse(**ud) for ud in downgrades],
        mixed=[UpgradeDowngradeResponse(**ud) for ud in mixed_detailed],
        unresolved=[UpgradeDowngradeResponse(**ud) for ud in mixed_bare],
        total=len(uds),
        grade_counts=grade_counts,
    )


@router.post("/upgrades-downgrades/reprocess")
def reprocess(conn: sqlite3.Connection = Depends(get_db)):
    count = reprocess_upgrades_downgrades(conn)
    return {"reprocessed": count}

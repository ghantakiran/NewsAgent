"""Catalyst endpoints — scored, ranked, price-confirmed market-moving events."""

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query

from ..core.deps import get_db
from ..services import catalyst_service
from ..services.catalyst_service import catalyst_stats, get_catalyst, get_catalysts
from ..services.grok_service import explain_catalyst, grok_status, squawk_now

router = APIRouter(prefix="/api/v1", tags=["catalysts"])

# Legacy category names kept working: the old endpoint filtered articles by
# category, so existing mobile clients keep sending these.
LEGACY_TYPE_MAP = {
    "earnings": ["earnings_beat", "earnings_miss", "earnings_results", "guidance_raise", "guidance_cut"],
    "fda": ["fda_approval", "fda_rejection", "clinical_positive", "clinical_negative", "clinical_hold", "pdufa_date"],
    "m&a": ["buyout_target", "acquirer", "merger_terminated", "strategic_review", "activist_stake", "spinoff"],
    "ipo": ["ipo_spac"],
    "insider": ["insider_buy", "insider_sell"],
    "dividend": ["dividend_initiation", "dividend_cut", "buyback"],
    "filing": ["sec_filing_8k", "offering", "shelf_atm", "restatement", "auditor_change"],
}


@router.get("/catalysts")
def list_catalysts(
    type: str | None = Query(None, description="Catalyst type, legacy category, or 'all'"),
    group: str | None = Query(None, description="deal|clinical|capital|operating|legal|analyst|structural|macro"),
    direction: str | None = Query(None, description="bullish|bearish|neutral"),
    ticker: str | None = Query(None),
    search: str | None = Query(None),
    min_score: float = Query(0, ge=0, le=100),
    confirmed_only: bool = Query(False, description="Only events the tape has confirmed"),
    order: str = Query("score", description="score|time|move"),
    hours: float = Query(48, gt=0, le=720),
    limit: int = Query(100, le=500),
    conn: sqlite3.Connection = Depends(get_db),
):
    types = None
    if type and type != "all":
        types = LEGACY_TYPE_MAP.get(type.lower(), [type])
    catalysts = get_catalysts(
        conn, hours=hours, min_score=min_score, types=types,
        groups=[group] if group else None, direction=direction,
        ticker=ticker, search=search, confirmed_only=confirmed_only,
        order=order, limit=limit,
    )
    return {"catalysts": catalysts, "total": len(catalysts)}


@router.get("/catalysts/stats")
def catalysts_stats(
    hours: float = Query(24, gt=0, le=720),
    conn: sqlite3.Connection = Depends(get_db),
):
    stats = catalyst_stats(conn, hours=hours)
    last = catalyst_service.last_run()
    stats["last_scan"] = last.isoformat() if last else None
    return stats


@router.get("/catalysts/{catalyst_id}")
def catalyst_detail(catalyst_id: str, conn: sqlite3.Connection = Depends(get_db)):
    catalyst = get_catalyst(conn, catalyst_id)
    if catalyst is None:
        raise HTTPException(status_code=404, detail="Catalyst not found")
    return catalyst


@router.post("/catalysts/scan")
def scan_now(
    with_quotes: bool = Query(True),
    hours: float = Query(48, gt=0, le=720),
    conn: sqlite3.Connection = Depends(get_db),
):
    """Re-run detection over the cached articles immediately."""
    new, rescored = catalyst_service.refresh_catalysts(conn, hours=hours, with_quotes=with_quotes)
    return {"new": new, "rescored": rescored}


@router.get("/catalysts/grok/status")
def grok_state():
    """Whether Grok live search is configured, and with which model."""
    return grok_status()


@router.post("/catalysts/grok/squawk")
def grok_squawk(
    minutes: int = Query(30, ge=1, le=180, description="How far back to search X and the web"),
    conn: sqlite3.Connection = Depends(get_db),
):
    """Pull breaking events off X, store them, and re-rank the board.

    X carries halts, leaks and filings before the wires do, so these items enter
    the same pipeline as any headline and cluster with the wire story when it
    lands.
    """
    stored, detected = squawk_now(conn, minutes=minutes)
    return {"stored": stored, "catalysts_detected": detected}


@router.get("/catalysts/{catalyst_id}/explain")
def explain(catalyst_id: str, conn: sqlite3.Connection = Depends(get_db)):
    """Ask Grok what is actually moving this name, with citations."""
    catalyst = get_catalyst(conn, catalyst_id)
    if catalyst is None:
        raise HTTPException(status_code=404, detail="Catalyst not found")
    return explain_catalyst(catalyst)

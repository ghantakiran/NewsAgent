"""TradingView inbound alert webhook + dashboard read endpoints.

TradingView fires an alert -> POST here -> normalize -> coalesce into a group
-> persist snapshot -> broadcast over the existing live WebSocket. A burst of
alerts for the same group key collapses into one updating card (see
services/alert_coalescer.py). Optionally forwards to the existing Discord
routes so TradingView's direct Discord webhook can be retired.

Auth: TradingView's free tier can't send custom headers, so the shared secret
is a ?token= query param (or a "token" field in the JSON body). Compared in
constant time. If TRADINGVIEW_WEBHOOK_TOKEN is unset the endpoint 503s rather
than accepting unauthenticated alerts.
"""

import hmac
import json
import logging
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from starlette.concurrency import run_in_threadpool

from ..config import TRADINGVIEW_FORWARD_DISCORD, TRADINGVIEW_WEBHOOK_TOKEN
from ..core.database import get_recent_alert_groups, upsert_alert_group
from ..core.deps import get_db
from ..models.schemas import AlertGroupListResponse, AlertGroupResponse
from ..services import alert_coalescer
from ..routers.websocket import broadcast_alert

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["tradingview"])

MAX_BODY_BYTES = 16 * 1024  # reject oversized webhook bodies before parsing
_MAX_FIELD = 280            # cap untrusted string fields written to DB / broadcast


def _check_token(token: str) -> None:
    if not TRADINGVIEW_WEBHOOK_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="TradingView webhook not configured (set TRADINGVIEW_WEBHOOK_TOKEN)",
        )
    if not token or not hmac.compare_digest(token, TRADINGVIEW_WEBHOOK_TOKEN):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid token")


def _clip(s: str, n: int = _MAX_FIELD) -> str:
    return s[:n]


def _normalize(raw: dict) -> dict:
    """Map an arbitrary inbound payload to the fields the coalescer expects.
    Untrusted strings are length-capped before they reach the DB / broadcast."""
    # aliases are consumed (not retained in extra) so they don't duplicate
    known = {"ticker", "symbol", "category", "signal", "action", "timeframe",
             "tf", "price", "message", "msg", "token"}
    ticker = _clip(str(raw.get("ticker") or raw.get("symbol") or "").upper().strip(), 16)
    price = raw.get("price")
    try:
        price = float(price) if price not in (None, "") else None
    except (TypeError, ValueError):
        price = None
    extra = {str(k)[:64]: (v[:_MAX_FIELD] if isinstance(v, str) else v)
             for k, v in raw.items() if k not in known}
    return {
        "ticker": ticker,
        "category": _clip(str(raw.get("category") or "general").lower().strip(), 32),
        "signal": _clip(str(raw.get("signal") or raw.get("action") or "").lower().strip(), 32),
        "timeframe": _clip(str(raw.get("timeframe") or raw.get("tf") or "").strip(), 16),
        "price": price,
        "message": _clip(str(raw.get("message") or raw.get("msg") or "").strip()),
        "extra": dict(list(extra.items())[:30]),  # bound extra-key count
    }


def _parse_body(body: bytes) -> dict:
    """Accept JSON, or fall back to a plain-text TradingView message."""
    text = body.decode("utf-8", errors="replace").strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {"message": text}
    except json.JSONDecodeError:
        return {"message": text}


@router.post("/webhook/tradingview")
async def tradingview_webhook(
    request: Request,
    token: str | None = Query(None),
    conn: sqlite3.Connection = Depends(get_db),
):
    body = await request.body()
    if len(body) > MAX_BODY_BYTES:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="body too large")
    # Validate the query token before parsing untrusted body; only parse the
    # body for a token fallback when the query token is absent.
    if token:
        _check_token(token)
        raw = _parse_body(body)
    else:
        raw = _parse_body(body)
        _check_token(raw.get("token", ""))

    alert = _normalize(raw)
    event, group = alert_coalescer.coalesce(alert)

    await run_in_threadpool(upsert_alert_group, conn, group)
    await broadcast_alert(event, group)

    if TRADINGVIEW_FORWARD_DISCORD:
        try:
            from ..services import discord_service
            discord_service.enqueue_article({
                "id": f"tv-{group['group_id']}-{group['count']}",
                "title": (alert.get("message") or f"{alert['ticker']} {alert['signal']}".strip()
                          or "TradingView alert"),
                "url": "",
                "source": "TradingView",
                "published": group["last_seen"],
                "category": alert["category"],
                "tickers": [alert["ticker"]] if alert["ticker"] else [],
                "summary": alert.get("message", ""),
            })
        except Exception as e:
            logger.warning(f"TradingView->Discord forward failed: {e}")

    return {"status": "ok", "event": event, "group_id": group["group_id"], "count": group["count"]}


@router.get("/alerts", response_model=AlertGroupListResponse)
def list_alert_groups(
    limit: int = Query(100, ge=1, le=500),
    hours: int = Query(24, ge=1, le=168),
    conn: sqlite3.Connection = Depends(get_db),
):
    """Recent coalesced alert groups — used by the dashboard to backfill cards
    on connect before the live WebSocket stream takes over."""
    groups = get_recent_alert_groups(conn, limit=limit, hours=hours)
    return AlertGroupListResponse(
        groups=[AlertGroupResponse(**g) for g in groups],
        total=len(groups),
    )

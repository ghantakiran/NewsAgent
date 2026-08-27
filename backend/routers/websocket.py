"""WebSocket endpoint for real-time article streaming.

Clients connect and receive new articles as they're fetched from RSS feeds.
Supports optional ticker filtering via query parameter.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])

# Connected clients
_clients: set[WebSocket] = set()
_client_filters: dict[int, set[str]] = {}  # ws id -> set of tickers to filter


@router.websocket("/api/v1/ws/live")
async def websocket_live(
    websocket: WebSocket,
    tickers: str | None = Query(None, description="Comma-separated tickers to filter"),
):
    """WebSocket endpoint for live article updates.

    Connect: ws://host/api/v1/ws/live?tickers=AAPL,NVDA

    Receives JSON messages:
    - {"type": "article", "data": {...article fields...}}
    - {"type": "ud", "data": {...upgrade/downgrade fields...}}
    - {"type": "ping"}

    Send messages:
    - {"type": "subscribe", "tickers": ["AAPL", "NVDA"]}
    - {"type": "unsubscribe", "tickers": ["AAPL"]}
    """
    await websocket.accept()
    _clients.add(websocket)

    # Set initial filter
    ws_id = id(websocket)
    if tickers:
        _client_filters[ws_id] = {t.strip().upper() for t in tickers.split(",")}
    else:
        _client_filters[ws_id] = set()  # empty = receive all

    logger.info(f"WebSocket client connected (total: {len(_clients)})")

    try:
        while True:
            # Listen for client messages (subscribe/unsubscribe)
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30)
                msg = json.loads(data)

                if msg.get("type") == "subscribe":
                    new_tickers = {t.upper() for t in msg.get("tickers", [])}
                    _client_filters[ws_id] |= new_tickers
                    await websocket.send_json({"type": "subscribed", "tickers": list(_client_filters[ws_id])})

                elif msg.get("type") == "unsubscribe":
                    rm_tickers = {t.upper() for t in msg.get("tickers", [])}
                    _client_filters[ws_id] -= rm_tickers
                    await websocket.send_json({"type": "subscribed", "tickers": list(_client_filters[ws_id])})

            except asyncio.TimeoutError:
                # Send ping to keep connection alive
                try:
                    await websocket.send_json({"type": "ping", "time": datetime.now(timezone.utc).isoformat()})
                except Exception:
                    break

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning(f"WebSocket error: {e}")
    finally:
        _clients.discard(websocket)
        _client_filters.pop(ws_id, None)
        logger.info(f"WebSocket client disconnected (total: {len(_clients)})")


async def broadcast_article(article: dict) -> int:
    """Broadcast a new article to all connected WebSocket clients.

    Filters by client's subscribed tickers. Returns number of clients notified.
    """
    if not _clients:
        return 0

    article_tickers = set(article.get("tickers", []))
    published = article.get("published")
    if isinstance(published, datetime):
        published = published.isoformat()

    payload = json.dumps({
        "type": "article",
        "data": {
            "id": article.get("id"),
            "title": article.get("title"),
            "url": article.get("url"),
            "source": article.get("source"),
            "published": published,
            "category": article.get("category"),
            "tickers": article.get("tickers", []),
            "summary": article.get("summary", ""),
        },
    })

    sent = 0
    dead_clients = set()

    for ws in _clients.copy():
        ws_id = id(ws)
        client_filter = _client_filters.get(ws_id, set())

        # Send if: no filter (receive all) OR any ticker matches
        if not client_filter or article_tickers & client_filter:
            try:
                await ws.send_text(payload)
                sent += 1
            except Exception:
                dead_clients.add(ws)

    # Clean up dead connections
    for ws in dead_clients:
        _clients.discard(ws)
        _client_filters.pop(id(ws), None)

    return sent


async def broadcast_alert(event: str, group: dict) -> int:
    """Broadcast a coalesced alert group to connected clients.

    event is "new" (open a card) or "update" (patch the card with this group_id).
    Frontend keys cards by group["group_id"]: on "new" it inserts, on "update"
    it mutates the existing card in place (count, latest, last_seen) and flashes.
    Filtered by the group's ticker against each client's subscription.
    """
    if not _clients:
        return 0

    ticker = (group.get("ticker") or "").upper()
    payload = json.dumps({
        "type": "alert",
        "event": event,  # "new" | "update"
        "data": group,
    })

    sent = 0
    dead_clients = set()
    for ws in _clients.copy():
        client_filter = _client_filters.get(id(ws), set())
        if not client_filter or (ticker and ticker in client_filter):
            try:
                await ws.send_text(payload)
                sent += 1
            except Exception:
                dead_clients.add(ws)

    for ws in dead_clients:
        _clients.discard(ws)
        _client_filters.pop(id(ws), None)

    return sent


async def broadcast_ud(ud: dict) -> int:
    """Broadcast a new upgrade/downgrade to connected clients."""
    if not _clients:
        return 0

    published = ud.get("published")
    if isinstance(published, datetime):
        published = published.isoformat()

    payload = json.dumps({
        "type": "ud",
        "data": {
            "ticker": ud.get("ticker"),
            "firm": ud.get("firm"),
            "action": ud.get("action"),
            "old_rating": ud.get("old_rating", ""),
            "new_rating": ud.get("new_rating", ""),
            "price_target": ud.get("price_target", ""),
            "published": published,
            "source_url": ud.get("source_url", ""),
            "source": ud.get("source", ""),
        },
    })

    sent = 0
    dead_clients = set()

    for ws in _clients.copy():
        ws_id = id(ws)
        client_filter = _client_filters.get(ws_id, set())
        ticker = ud.get("ticker", "").upper()

        if not client_filter or ticker in client_filter:
            try:
                await ws.send_text(payload)
                sent += 1
            except Exception:
                dead_clients.add(ws)

    for ws in dead_clients:
        _clients.discard(ws)
        _client_filters.pop(id(ws), None)

    return sent

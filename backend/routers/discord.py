"""Discord endpoints — per-category webhook route config + signed interactions.

Route config (GET/PUT/DELETE/test) is JWT-authed and powers the same "Discord"
screen on mobile that the Streamlit app exposes. The interactions endpoint is
public but Ed25519-signature-verified (Discord requirement), not JWT-authed.
"""
import json
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Request, status

from ..config import DISCORD_PUBLIC_KEY
from ..core.database import (
    delete_discord_route,
    get_discord_route,
    get_discord_routes,
    save_discord_route,
)
from ..core.deps import get_db, require_auth
from ..models.schemas import (
    DiscordRouteListResponse,
    DiscordRouteResponse,
    DiscordRouteUpdate,
    DiscordTestRequest,
    DiscordTestResponse,
)
from ..services import discord_commands, discord_service

router = APIRouter(prefix="/api/v1/discord", tags=["discord"])

CATEGORIES = discord_commands.CATEGORIES


def _mask(url: str) -> str:
    url = url or ""
    return f"…{url[-6:]}" if len(url) > 6 else ("set" if url else "")


def _to_response(category: str, row: dict | None) -> DiscordRouteResponse:
    if not row:
        return DiscordRouteResponse(category=category)
    return DiscordRouteResponse(
        category=category,
        configured=bool(row.get("webhook_url")),
        enabled=bool(row.get("enabled")),
        disabled=bool(row.get("disabled")),
        fail_count=int(row.get("fail_count") or 0),
        masked_url=_mask(row.get("webhook_url", "")),
        updated_at=row.get("updated_at"),
    )


@router.get("/categories")
def list_categories():
    return {"categories": CATEGORIES}


@router.get("/routes", response_model=DiscordRouteListResponse)
def list_routes(
    user: dict = Depends(require_auth),
    conn: sqlite3.Connection = Depends(get_db),
):
    by_cat = {r["category"]: r for r in get_discord_routes(conn)}
    routes = [_to_response(c, by_cat.get(c)) for c in CATEGORIES]
    return DiscordRouteListResponse(routes=routes, categories=CATEGORIES)


@router.put("/routes/{category}", response_model=DiscordRouteResponse)
def upsert_route(
    category: str,
    data: DiscordRouteUpdate,
    user: dict = Depends(require_auth),
    conn: sqlite3.Connection = Depends(get_db),
):
    if category not in CATEGORIES:
        raise HTTPException(status_code=400, detail=f"Unknown category: {category}")
    if not data.webhook_url.strip():
        raise HTTPException(status_code=400, detail="webhook_url is required")
    save_discord_route(conn, category, data.webhook_url, data.enabled)
    return _to_response(category, get_discord_route(conn, category))


@router.delete("/routes/{category}")
def remove_route(
    category: str,
    user: dict = Depends(require_auth),
    conn: sqlite3.Connection = Depends(get_db),
):
    delete_discord_route(conn, category)
    return {"status": "ok"}


@router.post("/routes/{category}/test", response_model=DiscordTestResponse)
async def test_route(
    category: str,
    data: DiscordTestRequest,
    user: dict = Depends(require_auth),
    conn: sqlite3.Connection = Depends(get_db),
):
    url = (data.webhook_url or "").strip()
    if not url:
        row = get_discord_route(conn, category)
        url = (row or {}).get("webhook_url", "")
    if not url:
        raise HTTPException(status_code=400, detail="No webhook URL to test")
    ok, message = await discord_service.post_test(url, category)
    return DiscordTestResponse(ok=ok, message=message)


@router.post("/interactions")
async def interactions(
    request: Request,
    conn: sqlite3.Connection = Depends(get_db),
):
    """Discord slash-command webhook. Public but Ed25519-signature-verified."""
    signature = request.headers.get("X-Signature-Ed25519", "")
    timestamp = request.headers.get("X-Signature-Timestamp", "")
    body = await request.body()
    if not discord_commands.verify_signature(DISCORD_PUBLIC_KEY, signature, timestamp, body):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid request signature")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="invalid payload")
    return discord_commands.handle_interaction(payload, conn)

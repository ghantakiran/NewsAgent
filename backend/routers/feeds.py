"""Feed management endpoints."""

import sqlite3
from pathlib import Path

import toml
from fastapi import APIRouter, Depends, HTTPException

from ..config import CONFIG_DIR
from ..core.database import delete_custom_feed, get_custom_feeds, save_custom_feed, toggle_custom_feed
from ..core.deps import get_db
from ..models.schemas import CustomFeedCreate, CustomFeedUpdate, FeedListResponse, FeedResponse
from ..services.feed_service import get_fetch_errors

router = APIRouter(prefix="/api/v1", tags=["feeds"])


def _load_default_feeds() -> list[dict]:
    path = CONFIG_DIR / "default_feeds.toml"
    if not path.exists():
        return []
    data = toml.load(str(path))
    return [
        {"name": f["name"], "url": f["url"], "category": f.get("category", "general"),
         "enabled": f.get("enabled", True)}
        for f in data.get("feeds", [])
    ]


@router.get("/feeds", response_model=FeedListResponse)
def list_feeds(conn: sqlite3.Connection = Depends(get_db)):
    defaults = _load_default_feeds()
    customs = get_custom_feeds(conn)
    errors = get_fetch_errors()

    feeds = []
    for f in defaults:
        feeds.append(FeedResponse(
            name=f["name"], url=f["url"], category=f["category"],
            enabled=f["enabled"], error=errors.get(f["name"]), is_custom=False,
        ))
    for f in customs:
        feeds.append(FeedResponse(
            name=f["name"], url=f["url"], category=f.get("category", "general"),
            enabled=bool(f.get("enabled", 1)), error=errors.get(f["name"]), is_custom=True,
        ))

    return FeedListResponse(feeds=feeds, errors=errors)


@router.post("/feeds/custom")
def add_custom_feed(feed: CustomFeedCreate, conn: sqlite3.Connection = Depends(get_db)):
    save_custom_feed(conn, feed.name, feed.url, feed.category, True)
    return {"status": "ok", "name": feed.name}


@router.delete("/feeds/custom/{name}")
def remove_custom_feed(name: str, conn: sqlite3.Connection = Depends(get_db)):
    delete_custom_feed(conn, name)
    return {"status": "ok"}


@router.patch("/feeds/custom/{name}")
def update_custom_feed(name: str, update: CustomFeedUpdate, conn: sqlite3.Connection = Depends(get_db)):
    if update.enabled is not None:
        toggle_custom_feed(conn, name, update.enabled)
    return {"status": "ok"}

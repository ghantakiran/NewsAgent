"""User endpoints — watchlist and settings."""

import sqlite3

from fastapi import APIRouter, Depends

from ..core.database import get_user_settings, get_watchlist, set_watchlist, update_user_settings
from ..core.deps import get_db, require_auth
from ..models.schemas import UserSettingsResponse, UserSettingsUpdate, WatchlistResponse, WatchlistUpdate

router = APIRouter(prefix="/api/v1/user", tags=["user"])


@router.get("/watchlist", response_model=WatchlistResponse)
def get_user_watchlist(
    user: dict = Depends(require_auth),
    conn: sqlite3.Connection = Depends(get_db),
):
    tickers = get_watchlist(conn, user["id"])
    return WatchlistResponse(tickers=tickers)


@router.put("/watchlist", response_model=WatchlistResponse)
def update_watchlist(
    data: WatchlistUpdate,
    user: dict = Depends(require_auth),
    conn: sqlite3.Connection = Depends(get_db),
):
    set_watchlist(conn, user["id"], data.tickers)
    return WatchlistResponse(tickers=data.tickers)


@router.get("/settings", response_model=UserSettingsResponse)
def get_settings(
    user: dict = Depends(require_auth),
    conn: sqlite3.Connection = Depends(get_db),
):
    settings = get_user_settings(conn, user["id"])
    return UserSettingsResponse(**settings)


@router.put("/settings", response_model=UserSettingsResponse)
def update_settings(
    data: UserSettingsUpdate,
    user: dict = Depends(require_auth),
    conn: sqlite3.Connection = Depends(get_db),
):
    update_user_settings(conn, user["id"], tz=data.timezone, notif_prefs=data.notification_prefs)
    settings = get_user_settings(conn, user["id"])
    return UserSettingsResponse(**settings)

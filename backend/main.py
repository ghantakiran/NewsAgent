"""NewsAgent FastAPI backend — main entry point.

Run with: uvicorn backend.main:app --reload
"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

import toml
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import (
    ALERT_PRUNE_AFTER_DAYS,
    CATALYST_ALERT_MAX_AGE_HOURS,
    CATALYST_ALERT_MIN_SCORE,
    CATALYST_ALERTS_ENABLED,
    CONFIG_DIR,
    CORS_ORIGINS,
)
from .core.database import (
    get_connection,
    get_recent_alert_groups,
    init_db,
    insert_article,
    insert_upgrade_downgrade,
    prune_old_alert_groups,
    prune_old_articles,
)
from .routers import articles, auth, catalysts, discord, earnings, feeds, notifications, stats, tradingview, upgrades, users, websocket
from .routers.websocket import broadcast_article
from .services import alert_coalescer, catalyst_service, discord_service
from .services.feed_service import FeedRefresher, fetch_all_feeds
from .services.notification_service import check_and_notify, init_firebase

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("newsagent")

# Global refresher reference
_refresher: FeedRefresher | None = None
# The refresher runs on a worker thread; alerts must be posted on the loop.
_dispatch_loop: asyncio.AbstractEventLoop | None = None


def _load_settings() -> dict:
    path = CONFIG_DIR / "settings.toml"
    if not path.exists():
        return {"general": {"refresh_interval": 15, "max_articles": 500, "prune_after_days": 7}}
    return toml.load(str(path))


def _load_all_feeds_as_dicts() -> list[dict]:
    """Load default + custom feeds as list of dicts."""
    # Default feeds
    default_path = CONFIG_DIR / "default_feeds.toml"
    feed_dicts = []
    if default_path.exists():
        data = toml.load(str(default_path))
        for f in data.get("feeds", []):
            feed_dicts.append({
                "name": f["name"], "url": f["url"],
                "category": f.get("category", "general"),
                "enabled": f.get("enabled", True),
            })
    # Custom feeds from DB
    conn = get_connection()
    from .core.database import get_custom_feeds
    customs = get_custom_feeds(conn)
    conn.close()
    for f in customs:
        feed_dicts.append({
            "name": f["name"], "url": f["url"],
            "category": f.get("category", "general"),
            "enabled": bool(f.get("enabled", 1)),
        })
    return feed_dicts


def _make_insert_fn():
    """Create a closure that inserts articles into the database."""
    def insert_fn(article: dict) -> bool:
        conn = get_connection()
        try:
            inserted = insert_article(conn, article)
            if inserted:
                try:
                    check_and_notify(article, conn)
                except Exception as e:
                    logger.warning(f"Notification check failed: {e}")
                # Broadcast to WebSocket clients (fire-and-forget)
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        asyncio.ensure_future(broadcast_article(article))
                except Exception:
                    pass
                # Push to Discord webhooks (fire-and-forget; thread-safe)
                try:
                    discord_service.enqueue_article(article)
                except Exception as e:
                    logger.warning(f"Discord enqueue failed: {e}")
            return inserted
        finally:
            conn.close()
    return insert_fn


def _make_insert_ud_fn():
    """Create a closure that inserts upgrade/downgrade records."""
    def insert_ud_fn(ud: dict) -> None:
        conn = get_connection()
        try:
            insert_upgrade_downgrade(conn, ud)
        finally:
            conn.close()
    return insert_ud_fn


def _make_catalyst_fn():
    """Closure the refresher calls each cycle to re-rank the catalyst board."""
    def catalyst_fn() -> tuple[int, int]:
        conn = get_connection()
        try:
            counts = catalyst_service.refresh_catalysts(conn)
            _dispatch_catalyst_alerts(conn)
            return counts
        finally:
            conn.close()
    return catalyst_fn


def _dispatch_catalyst_alerts(conn) -> None:
    """Ping Discord once per high-impact catalyst.

    Unlike the article stream this is deliberately quiet: an event has to clear
    the score threshold, and `mark_alerted` guarantees it is never sent twice.
    """
    if not CATALYST_ALERTS_ENABLED:
        return
    try:
        pending = catalyst_service.pending_alerts(
            conn,
            min_score=CATALYST_ALERT_MIN_SCORE,
            hours=CATALYST_ALERT_MAX_AGE_HOURS,
        )
        if not pending:
            return
        loop = _dispatch_loop
        if loop is None or not loop.is_running():
            return
        future = asyncio.run_coroutine_threadsafe(
            discord_service.post_catalysts(conn, pending), loop
        )
        sent = future.result(timeout=30)
        if sent:
            catalyst_service.mark_alerted(conn, pending[:sent], channel="discord")
            logger.info(f"Alerted {sent} catalyst(s) to Discord")
    except Exception as e:
        logger.warning(f"Catalyst alerting failed: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: init DB, prune old articles, start background feed refresher."""
    global _refresher

    # Init database
    conn = get_connection()
    init_db(conn)

    # Prune old articles
    settings = _load_settings()
    prune_days = settings.get("general", {}).get("prune_after_days", 7)
    prune_old_articles(conn, prune_days)
    prune_old_alert_groups(conn, ALERT_PRUNE_AFTER_DAYS)
    # Seed the in-memory coalescer from persisted alert groups so a restart
    # keeps recent episode cards live instead of dropping them.
    alert_coalescer.hydrate(get_recent_alert_groups(conn, limit=200, hours=24))
    conn.close()

    # Initialize Firebase for push notifications (no-op if not configured)
    init_firebase(os.getenv("FIREBASE_CREDENTIALS_PATH", ""))

    # Start the Discord webhook dispatcher on the running event loop (no-op if disabled)
    global _dispatch_loop
    _dispatch_loop = asyncio.get_running_loop()
    discord_service.start_dispatcher(_dispatch_loop)

    # Load feeds and do initial fetch
    feed_dicts = _load_all_feeds_as_dicts()
    refresh_interval = settings.get("general", {}).get("refresh_interval", 15)

    insert_fn = _make_insert_fn()
    insert_ud_fn = _make_insert_ud_fn()

    # Initial synchronous fetch
    logger.info("Starting initial feed fetch...")
    fetch_all_feeds(feed_dicts, insert_fn, insert_ud_fn)
    logger.info("Initial fetch complete.")

    # Seed the catalyst board from what the initial fetch just cached. Quotes are
    # skipped here so startup stays fast; the refresher attaches them next cycle.
    conn = get_connection()
    try:
        catalyst_service.init_catalyst_tables(conn)
        catalyst_service.prune_catalysts(conn, prune_days)
        new_catalysts, _ = catalyst_service.refresh_catalysts(conn, with_quotes=False)
        logger.info(f"Catalyst board seeded ({new_catalysts} events)")
    except Exception as e:
        logger.warning(f"Catalyst seeding failed: {e}")
    finally:
        conn.close()

    # Start background refresher
    _refresher = FeedRefresher(
        feeds=feed_dicts,
        interval=refresh_interval,
        insert_fn=insert_fn,
        insert_ud_fn=insert_ud_fn,
        catalyst_fn=_make_catalyst_fn(),
    )
    _refresher.start()
    logger.info(f"Feed refresher started (interval={refresh_interval}s)")

    yield

    # Shutdown
    if _refresher:
        _refresher.stop()
        logger.info("Feed refresher stopped.")
    await discord_service.stop_dispatcher()


app = FastAPI(
    title="NewsAgent API",
    description="Real-time stock market news aggregator API",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(articles.router)
app.include_router(upgrades.router)
app.include_router(earnings.router)
app.include_router(catalysts.router)
app.include_router(feeds.router)
app.include_router(stats.router)
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(notifications.router)
app.include_router(discord.router)
app.include_router(tradingview.router)
app.include_router(websocket.router)


@app.get("/")
def root():
    return {"app": "NewsAgent API", "version": "1.0.0", "docs": "/docs", "dashboard": "/dashboard"}


# Live alerts dashboard (single-file, zero-build). Served same-origin so its
# relative WebSocket + /api/v1 calls hit this app directly.
_STATIC_DIR = Path(__file__).parent / "static"
_STATIC_DIR.mkdir(parents=True, exist_ok=True)  # avoid mount crash on fresh clones


@app.get("/dashboard")
def dashboard():
    return FileResponse(_STATIC_DIR / "dashboard.html")


app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

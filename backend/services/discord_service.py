"""Outbound Discord webhook push for new articles, routed by category.

Stateless, minimal-dependency design (httpx only — already a project dependency).
One webhook URL per news category lives in the ``discord_routes`` table (edited
from the Streamlit "Discord" page), with an optional ``DISCORD_WEBHOOK_<CATEGORY>``
env-var fallback.

New articles are enqueued from the feed-refresh worker thread and drained by a
single asyncio worker that:
  - skips backlog via a freshness window (DISCORD_MAX_AGE_MINUTES),
  - dedups via the ``discord_sent`` table (Article.id is a stable URL hash),
  - batches up to 10 embeds per webhook POST,
  - throttles each webhook (~24 msgs/min, under Discord's 30/min cap),
  - honours 429 Retry-After,
  - disables a route after N consecutive failures (deleted webhook, etc.).

Discord latency or outages never block feed ingestion: enqueue is fire-and-forget
and all delivery happens off the ingestion path on the event loop.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone

import httpx

from ..config import (
    DISCORD_AVATAR_URL,
    DISCORD_ENABLED,
    DISCORD_MAX_AGE_MINUTES,
    DISCORD_MAX_ROUTE_FAILURES,
    DISCORD_SENT_RETENTION_DAYS,
    DISCORD_THROTTLE_SECONDS,
    DISCORD_USERNAME,
)
from ..core.database import (
    bump_discord_route_failure,
    get_connection,
    get_discord_route,
    has_sent_to_discord,
    log_discord_sent,
    prune_discord_sent,
    reset_discord_route_failure,
)

logger = logging.getLogger(__name__)

MAX_EMBEDS = 10          # Discord hard limit: 10 embeds per message
HTTP_TIMEOUT = 10
BATCH_DRAIN_MAX = 50     # cap embeds processed per worker wake

# Embed colors per category, matching the UI's CATEGORY_COLORS (models.py) so a
# Discord post is the same color as the category badge in the app.
_COLORS = {
    "general": 0x9E9E9E, "earnings": 0xFFD700, "upgrade": 0x00C853,
    "downgrade": 0xFF1744, "macro": 0x2979FF, "fda": 0xAA00FF,
    "m&a": 0xFF9100, "ipo": 0x00E5FF, "insider": 0xFF6D00,
    "dividend": 0x76FF03, "filing": 0x8D6E63, "crypto": 0xF4511E,
    "tech": 0x7C4DFF,
}

_loop: asyncio.AbstractEventLoop | None = None
_queue: "asyncio.Queue[dict] | None" = None
_worker: asyncio.Task | None = None


# ── Lifecycle ────────────────────────────────────────────────────────────────

def start_dispatcher(loop: asyncio.AbstractEventLoop) -> None:
    """Start the background delivery worker on the given event loop."""
    global _loop, _queue, _worker
    if not DISCORD_ENABLED:
        logger.info("Discord push disabled (DISCORD_ENABLED=false)")
        return
    _loop = loop
    _queue = asyncio.Queue()
    _worker = loop.create_task(_run_worker())
    try:
        conn = get_connection()
        prune_discord_sent(conn, DISCORD_SENT_RETENTION_DAYS)
        conn.close()
    except Exception as e:  # pragma: no cover - best effort
        logger.warning(f"Discord sent-log prune failed: {e}")
    logger.info("Discord dispatcher started")


async def stop_dispatcher() -> None:
    global _worker
    if _worker is not None:
        _worker.cancel()
        try:
            await _worker
        except asyncio.CancelledError:
            pass
        _worker = None
        logger.info("Discord dispatcher stopped")


def enqueue_article(article: dict) -> None:
    """Thread-safe fire-and-forget. Called from the feed-refresh worker thread."""
    if not DISCORD_ENABLED or _queue is None or _loop is None:
        return
    if _too_old(article):
        return
    try:
        _loop.call_soon_threadsafe(_queue.put_nowait, article)
    except RuntimeError:
        pass  # loop is shutting down


# ── Worker ───────────────────────────────────────────────────────────────────

async def _run_worker() -> None:
    assert _queue is not None
    while True:
        first = await _queue.get()
        batch = [first]
        while len(batch) < BATCH_DRAIN_MAX and not _queue.empty():
            try:
                batch.append(_queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        try:
            await _process_batch(batch)
        except Exception as e:  # pragma: no cover - keep worker alive
            logger.error(f"Discord batch error: {e}")


async def _process_batch(batch: list[dict]) -> None:
    conn = get_connection()
    try:
        # Group new, routable embeds per destination webhook.
        groups: dict[str, dict] = {}
        for article in batch:
            aid = article.get("id")
            if not aid or has_sent_to_discord(conn, aid):
                continue
            category = article.get("category") or "general"
            resolved = _resolve_route(conn, category)
            if not resolved:
                continue
            webhook_url, route_cat = resolved
            g = groups.setdefault(webhook_url, {"embeds": [], "ids": [], "cat": route_cat})
            g["embeds"].append(_build_embed(article))
            g["ids"].append(aid)

        for webhook_url, g in groups.items():
            embeds, ids, cat = g["embeds"], g["ids"], g["cat"]
            for i in range(0, len(embeds), MAX_EMBEDS):
                chunk = embeds[i:i + MAX_EMBEDS]
                chunk_ids = ids[i:i + MAX_EMBEDS]
                if await _post_embeds(webhook_url, chunk):
                    reset_discord_route_failure(conn, cat)
                    for aid in chunk_ids:
                        log_discord_sent(conn, aid, cat)
                    await asyncio.sleep(DISCORD_THROTTLE_SECONDS)
                else:
                    fails = bump_discord_route_failure(conn, cat, DISCORD_MAX_ROUTE_FAILURES)
                    logger.warning(
                        f"Discord delivery failed for '{cat}' "
                        f"(failure {fails}/{DISCORD_MAX_ROUTE_FAILURES})"
                    )
                    break  # stop posting to a failing webhook this cycle
    finally:
        conn.close()


# ── Routing + payload ────────────────────────────────────────────────────────

def _resolve_route(conn, category: str) -> tuple[str, str] | None:
    """Resolve a category to (webhook_url, category_used).

    DB route first, then DISCORD_WEBHOOK_<CATEGORY> env var, falling back to the
    'general' route so nothing is silently dropped.
    """
    for cat in (category, "general"):
        row = get_discord_route(conn, cat)
        if row and row["webhook_url"] and row["enabled"] and not row["disabled"]:
            return row["webhook_url"], cat
        env_url = _env_webhook(cat)
        if env_url:
            return env_url, cat
    return None


def _env_webhook(category: str) -> str | None:
    slug = re.sub(r"[^A-Z0-9]", "", category.upper())  # 'm&a' -> 'MA'
    return os.getenv(f"DISCORD_WEBHOOK_{slug}") or None


def _build_embed(article: dict) -> dict:
    category = article.get("category") or "general"
    tickers = article.get("tickers") or []
    if isinstance(tickers, str):
        try:
            tickers = json.loads(tickers)
        except Exception:
            tickers = []

    embed: dict = {
        "title": (article.get("title") or "(no title)")[:256],
        "url": article.get("url") or "",
        "color": _COLORS.get(category, _COLORS["general"]),
        "timestamp": _iso(article.get("published")),
        "author": {"name": (article.get("source") or "NewsAgent")[:256]},
    }
    summary = (article.get("summary") or "").strip()
    if summary:
        embed["description"] = summary[:600]

    footer_bits = [category.upper()]
    if tickers:
        footer_bits.append(" ".join(f"${t}" for t in tickers[:6]))
    embed["footer"] = {"text": " · ".join(footer_bits)[:2048]}
    return embed


async def post_test(webhook_url: str, category: str = "general") -> tuple[bool, str]:
    """Server-side test post for the REST config endpoint."""
    embed = {
        "title": f"✅ NewsAgent connected — {category}",
        "description": "This channel will now receive NewsAgent market news for this category.",
        "color": _COLORS.get(category, _COLORS["general"]),
    }
    ok = await _post_embeds(webhook_url.strip(), [embed])
    return ok, ("Test message delivered" if ok else "Delivery failed — check the webhook URL")


def build_embed(article: dict) -> dict:
    """Public alias so command handlers can reuse the embed format."""
    return _build_embed(article)


async def _post_embeds(webhook_url: str, embeds: list[dict]) -> bool:
    payload: dict = {"username": DISCORD_USERNAME, "embeds": embeds}
    if DISCORD_AVATAR_URL:
        payload["avatar_url"] = DISCORD_AVATAR_URL
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            for _ in range(3):
                resp = await client.post(webhook_url, json=payload)
                if resp.status_code in (200, 204):
                    return True
                if resp.status_code == 429:
                    retry = _retry_after(resp)
                    logger.info(f"Discord 429, retrying in {retry:.1f}s")
                    await asyncio.sleep(retry)
                    continue
                logger.warning(f"Discord POST {resp.status_code}: {resp.text[:160]}")
                return False
    except httpx.HTTPError as e:
        logger.warning(f"Discord POST error: {e}")
    return False


# ── Helpers ──────────────────────────────────────────────────────────────────

def _retry_after(resp: httpx.Response) -> float:
    try:
        data = resp.json()
        if isinstance(data, dict) and "retry_after" in data:
            return min(float(data["retry_after"]), 30.0)
    except Exception:
        pass
    hdr = resp.headers.get("Retry-After")
    if hdr:
        try:
            return min(float(hdr), 30.0)
        except ValueError:
            pass
    return 2.0


def _parse_published(published) -> datetime | None:
    if not published:
        return None
    if isinstance(published, datetime):
        dt = published
    else:
        try:
            dt = datetime.fromisoformat(str(published))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _too_old(article: dict) -> bool:
    if DISCORD_MAX_AGE_MINUTES <= 0:
        return False
    dt = _parse_published(article.get("published"))
    if dt is None:
        return False
    return dt < datetime.now(timezone.utc) - timedelta(minutes=DISCORD_MAX_AGE_MINUTES)


def _iso(published) -> str:
    dt = _parse_published(published) or datetime.now(timezone.utc)
    return dt.isoformat()

# ── Catalyst alerts ──────────────────────────────────────────────────────────
# Articles stream to Discord as they arrive; catalysts are different. Only a
# high-impact, scored *event* is worth a ping, and each one pings exactly once.

_DIRECTION_MARK = {"bullish": "▲", "bearish": "▼", "neutral": "■"}
_CATALYST_COLORS = {"bullish": 0x00E59A, "bearish": 0xFF2D55, "neutral": 0xF5C542}


def build_catalyst_embed(catalyst: dict) -> dict:
    """Discord embed for one scored catalyst."""
    direction = catalyst.get("direction") or "neutral"
    ticker = catalyst.get("ticker") or "MARKET"
    mark = _DIRECTION_MARK.get(direction, "■")
    score = catalyst.get("score") or 0

    embed: dict = {
        "title": f"{mark} {ticker} · {catalyst.get('label', 'Catalyst')} · {score:.0f}/100"[:256],
        "description": (catalyst.get("headline") or "")[:600],
        "url": catalyst.get("url") or "",
        "color": _CATALYST_COLORS.get(direction, _CATALYST_COLORS["neutral"]),
        "timestamp": _iso(catalyst.get("published")),
        "author": {"name": "NewsAgent · Catalyst Board"},
    }

    fields = []
    change = catalyst.get("change_pct")
    if change is not None:
        move = f"{change:+.2f}%"
        rvol = catalyst.get("rel_volume") or 0
        if rvol >= 1.5:
            move += f" on {rvol:.1f}x volume"
        fields.append({"name": "Tape", "value": move, "inline": True})
    if catalyst.get("company"):
        fields.append({"name": "Company", "value": catalyst["company"][:64], "inline": True})
    facts = catalyst.get("facts") or {}
    detail = " · ".join(str(v) for k, v in facts.items() if k not in ("company", "filing"))
    if detail:
        fields.append({"name": "Detail", "value": detail[:256], "inline": False})
    if fields:
        embed["fields"] = fields[:4]

    footer = [f"{catalyst.get('source_count', 1)} source(s)"]
    if catalyst.get("confirmed"):
        footer.append("price-confirmed")
    embed["footer"] = {"text": " · ".join(footer)[:2048]}
    return embed


async def post_catalysts(conn, catalysts: list[dict]) -> int:
    """Deliver catalyst alerts, routed by group. Returns how many were sent.

    Routing reuses the per-category webhook config: a catalyst goes to its
    group's channel if one is set, otherwise to 'general'.
    """
    if not DISCORD_ENABLED or not catalysts:
        return 0
    by_route: dict[str, list[dict]] = {}
    for catalyst in catalysts:
        route = _resolve_route(conn, catalyst.get("catalyst_group") or "general")
        if route is None:
            continue
        by_route.setdefault(route[0], []).append(catalyst)

    sent = 0
    for webhook_url, group in by_route.items():
        embeds = [build_catalyst_embed(c) for c in group[:BATCH_DRAIN_MAX]]
        if await _post_embeds(webhook_url, embeds):
            sent += len(embeds)
    return sent

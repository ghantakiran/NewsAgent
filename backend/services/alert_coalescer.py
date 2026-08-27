"""Alert coalescing engine.

A burst ("episode") of alerts that share the same *group key* within a short
time window is collapsed into a single, updating card on the dashboard instead
of N separate rows. The first alert in a window opens a group ("new"); each
subsequent alert with the same key inside the window mutates that same group
("update") — bumping its count, refreshing `latest`, and appending to history.
Once the window lapses, the next matching alert opens a fresh group.

Group state lives in memory (single-process). It's also snapshotted to SQLite
via the persist callback so the dashboard can backfill recent cards on connect
and survive a restart. Thread-safe: a lock guards the in-memory map because the
webhook event loop and the feed refresher thread may both reach it.
"""

import hashlib
import threading
from datetime import datetime, timezone

from ..config import ALERT_HISTORY_LIMIT, COALESCE_GROUP_KEY, COALESCE_WINDOW_SECONDS

_lock = threading.Lock()
_groups: dict[str, dict] = {}  # group_id -> group snapshot

_KEY_FIELDS = [f.strip() for f in COALESCE_GROUP_KEY.split(",") if f.strip()]

# Bound in-memory growth: attacker-controlled (category, ticker) keys could
# otherwise create unbounded entries. Stale groups (no activity for a while)
# are evicted; a hard cap drops the oldest if the map still overflows.
_MAX_GROUPS = 5000
_STALE_SECONDS = max(COALESCE_WINDOW_SECONDS * 10, 3600)


def _snapshot(group: dict) -> dict:
    """Copy a group with its nested mutable containers detached, so concurrent
    serialization (DB write / WS broadcast) can't observe a mid-mutation map."""
    return {**group, "latest": dict(group["latest"]), "history": list(group["history"])}


def _evict_locked(now: datetime) -> None:
    """Drop stale groups; if still over cap, drop oldest by last_seen. Caller holds _lock."""
    if len(_groups) <= _MAX_GROUPS:
        return
    for gid in [g for g, v in _groups.items()
                if (now - datetime.fromisoformat(v["last_seen"])).total_seconds() > _STALE_SECONDS]:
        _groups.pop(gid, None)
    if len(_groups) > _MAX_GROUPS:
        for gid, _ in sorted(_groups.items(), key=lambda kv: kv[1]["last_seen"])[: len(_groups) - _MAX_GROUPS]:
            _groups.pop(gid, None)


def _group_id(alert: dict) -> str:
    """Stable id from the configured key fields (e.g. category+ticker)."""
    parts = [str(alert.get(f, "") or "").upper() for f in _KEY_FIELDS]
    raw = "|".join(parts)
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def coalesce(alert: dict) -> tuple[str, dict]:
    """Fold a normalized alert into its group.

    Returns (event, group_snapshot) where event is "new" or "update".
    `alert` must already be normalized (see tradingview router): it has
    category, ticker, timeframe, signal, price, message, received_at fields.
    """
    gid = _group_id(alert)
    now = _now()
    now_iso = now.isoformat()
    window = COALESCE_WINDOW_SECONDS

    with _lock:
        existing = _groups.get(gid)
        fresh = existing is not None
        if fresh:
            try:
                age = (now - datetime.fromisoformat(existing["last_seen"])).total_seconds()
                fresh = age <= window
            except (ValueError, TypeError):
                fresh = False  # malformed timestamp -> treat as a fresh window

        if fresh:
            existing["count"] += 1
            existing["last_seen"] = now_iso
            existing["latest"] = alert
            existing["history"] = (existing["history"] + [alert])[-ALERT_HISTORY_LIMIT:]
            return "update", _snapshot(existing)

        group = {
            "group_id": gid,
            "category": alert.get("category", "general"),
            "ticker": alert.get("ticker", ""),
            "timeframe": alert.get("timeframe", ""),
            "signal": alert.get("signal", ""),
            "count": 1,
            "first_seen": now_iso,
            "last_seen": now_iso,
            "latest": alert,
            "history": [alert],
        }
        _groups[gid] = group
        _evict_locked(now)
        return "new", _snapshot(group)


def hydrate(groups: list[dict]) -> None:
    """Seed the in-memory map from persisted snapshots on startup."""
    with _lock:
        for g in groups:
            _groups[g["group_id"]] = g


def active_groups() -> list[dict]:
    """Snapshot of all in-memory groups (most-recent first)."""
    with _lock:
        return sorted(
            (_snapshot(g) for g in _groups.values()),
            key=lambda g: g["last_seen"],
            reverse=True,
        )

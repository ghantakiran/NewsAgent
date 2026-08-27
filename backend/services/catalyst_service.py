"""Catalyst detection for the API — a thin wrapper over the shared engine.

The engine itself lives in `src/newsagent/catalysts` so the Streamlit app and
this backend rank events identically; only the plumbing (which DB connection,
which refresh loop) differs.
"""

from __future__ import annotations

import logging
import sqlite3
import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..config import DB_DIR, ROOT

# ROOT is the repository root (backend/config.py resolves it two levels up),
# so the shared engine sits at ROOT/src/newsagent/catalysts.
sys.path.insert(0, str(ROOT / "src"))

from newsagent.catalysts import (  # noqa: E402
    CatalystEngine,
    catalyst_stats,
    get_catalyst,
    get_catalysts,
    init_catalyst_tables,
    mark_alerted,
    pending_alerts,
    prune_catalysts,
    prune_stale_catalysts,
    upsert_catalysts,
)

logger = logging.getLogger(__name__)

_engine: CatalystEngine | None = None
_engine_lock = threading.Lock()
_last_run: datetime | None = None

__all__ = [
    "catalyst_stats", "get_catalyst", "get_catalysts", "get_engine",
    "init_catalyst_tables", "last_run", "mark_alerted", "pending_alerts",
    "prune_catalysts", "prune_stale_catalysts", "refresh_catalysts",
]


def get_engine() -> CatalystEngine:
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                _engine = CatalystEngine(Path(DB_DIR))
    return _engine


def last_run() -> datetime | None:
    return _last_run


def refresh_catalysts(
    conn: sqlite3.Connection,
    hours: float = 48,
    with_quotes: bool = True,
    limit: int = 1500,
) -> tuple[int, int]:
    """Re-derive and persist the catalyst ranking. Returns (new, rescored)."""
    global _last_run
    init_catalyst_tables(conn)
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    rows = conn.execute(
        "SELECT id, title, summary, source, url, published FROM articles "
        "WHERE published >= ? ORDER BY published DESC LIMIT ?",
        (cutoff, limit),
    ).fetchall()
    articles = [
        {"id": r[0], "title": r[1], "summary": r[2], "source": r[3], "url": r[4], "published": r[5]}
        for r in rows
    ]
    catalysts = get_engine().run(articles, with_quotes=with_quotes)
    counts = upsert_catalysts(conn, catalysts)
    # Keep the board equal to this scan's output — see prune_stale_catalysts.
    prune_stale_catalysts(conn, [c.id for c in catalysts], hours)
    _last_run = datetime.now(timezone.utc)
    return counts

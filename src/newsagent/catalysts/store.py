"""SQLite persistence for scored catalysts.

Catalysts are re-derived from the article cache on every refresh, so writes are
upserts: `first_seen` is preserved (it is what makes "new since you looked"
possible) while score, sources and quote are overwritten with the latest view.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Sequence
from datetime import datetime, timedelta, timezone
from typing import Any

from .engine import Catalyst
from .types import SPECS, CatalystType

SCHEMA = """
CREATE TABLE IF NOT EXISTS catalysts (
    id                TEXT PRIMARY KEY,
    ticker            TEXT NOT NULL DEFAULT '',
    company           TEXT NOT NULL DEFAULT '',
    type              TEXT NOT NULL,
    catalyst_group    TEXT NOT NULL DEFAULT '',
    direction         TEXT NOT NULL DEFAULT 'neutral',
    headline          TEXT NOT NULL,
    url               TEXT NOT NULL DEFAULT '',
    published         TEXT NOT NULL,
    latest            TEXT NOT NULL,
    first_seen        TEXT NOT NULL,
    updated_at        TEXT NOT NULL,
    score             REAL NOT NULL DEFAULT 0,
    detect_confidence REAL NOT NULL DEFAULT 0,
    ticker_confidence REAL NOT NULL DEFAULT 0,
    secondary_types   TEXT NOT NULL DEFAULT '[]',
    facts             TEXT NOT NULL DEFAULT '{}',
    score_parts       TEXT NOT NULL DEFAULT '{}',
    sources           TEXT NOT NULL DEFAULT '[]',
    source_count      INTEGER NOT NULL DEFAULT 1,
    price             REAL,
    change_pct        REAL,
    rel_volume        REAL,
    size_bucket       TEXT NOT NULL DEFAULT '',
    confirmed         INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_catalysts_score     ON catalysts(score DESC);
CREATE INDEX IF NOT EXISTS idx_catalysts_published ON catalysts(published DESC);
CREATE INDEX IF NOT EXISTS idx_catalysts_ticker    ON catalysts(ticker);
CREATE INDEX IF NOT EXISTS idx_catalysts_type      ON catalysts(type);

CREATE TABLE IF NOT EXISTS catalyst_alerts (
    catalyst_id TEXT PRIMARY KEY,
    sent_at     TEXT NOT NULL,
    score       REAL NOT NULL DEFAULT 0,
    channel     TEXT NOT NULL DEFAULT ''
);
"""

_COLUMNS = (
    "id", "ticker", "company", "type", "catalyst_group", "direction", "headline",
    "url", "published", "latest", "first_seen", "updated_at", "score",
    "detect_confidence", "ticker_confidence", "secondary_types", "facts",
    "score_parts", "sources", "source_count", "price", "change_pct",
    "rel_volume", "size_bucket", "confirmed",
)


def init_catalyst_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def _iso(dt: datetime) -> str:
    return (dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt).isoformat()


def _row_values(c: Catalyst, now: str) -> tuple:
    q = c.quote if c.quote and c.quote.ok else None
    return (
        c.id, c.ticker, c.company, c.type.value, c.group.value, c.direction.value,
        c.headline, c.url, _iso(c.published), _iso(c.latest), now, now,
        c.score, c.detect_confidence, c.ticker_confidence,
        json.dumps([t.value for t in c.secondary_types]), json.dumps(c.facts),
        json.dumps(c.score_parts), json.dumps([s.as_dict() for s in c.sources]),
        c.source_count,
        q.price if q else None, q.change_pct if q else None,
        q.rel_volume if q else None, q.size_bucket if q else "",
        int(c.confirmed),
    )


# Quote columns are written only by passes that actually fetched prices. A
# quote-less rescan (the fast path on page load) must not blank out a price the
# previous pass confirmed, so those columns fall back to the stored value.
_QUOTE_COLUMNS = ("price", "change_pct", "rel_volume")


def _update_clause(column: str) -> str:
    if column in _QUOTE_COLUMNS:
        return f"{column}=COALESCE(excluded.{column}, catalysts.{column})"
    if column == "size_bucket":
        return "size_bucket=COALESCE(NULLIF(excluded.size_bucket, ''), catalysts.size_bucket)"
    if column == "confirmed":
        return "confirmed=CASE WHEN excluded.price IS NULL THEN catalysts.confirmed ELSE excluded.confirmed END"
    if column == "score":
        # Likewise the score: a quote-less pass would drop the price factor.
        return "score=CASE WHEN excluded.price IS NULL AND catalysts.price IS NOT NULL THEN catalysts.score ELSE excluded.score END"
    return f"{column}=excluded.{column}"


def upsert_catalysts(conn: sqlite3.Connection, catalysts: Sequence[Catalyst]) -> tuple[int, int]:
    """Insert or refresh catalysts. Returns (inserted, updated)."""
    if not catalysts:
        return 0, 0
    now = _iso(datetime.now(timezone.utc))
    ids = [c.id for c in catalysts]
    placeholders = ",".join("?" * len(ids))
    existing = {
        r[0] for r in conn.execute(f"SELECT id FROM catalysts WHERE id IN ({placeholders})", ids)
    }
    # first_seen is deliberately absent from the update list: it records when we
    # first surfaced the event, which is what "new" badges and alerts key off.
    updatable = [c for c in _COLUMNS if c not in ("id", "first_seen")]
    conn.executemany(
        f"INSERT INTO catalysts ({','.join(_COLUMNS)}) VALUES ({','.join('?' * len(_COLUMNS))}) "
        f"ON CONFLICT(id) DO UPDATE SET {', '.join(_update_clause(c) for c in updatable)}",
        [_row_values(c, now) for c in catalysts],
    )
    conn.commit()
    inserted = len([c for c in catalysts if c.id not in existing])
    return inserted, len(catalysts) - inserted


def _decode(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    for key in ("secondary_types", "facts", "score_parts", "sources"):
        try:
            d[key] = json.loads(d.get(key) or ("[]" if key != "facts" and key != "score_parts" else "{}"))
        except (TypeError, ValueError):
            d[key] = [] if key in ("secondary_types", "sources") else {}
    ctype = d.get("type")
    spec = SPECS.get(CatalystType(ctype)) if ctype in {t.value for t in CatalystType} else None
    d["label"] = spec.label if spec else (ctype or "").replace("_", " ").title()
    d["color"] = spec.color if spec else "#8b93b0"
    d["impact"] = spec.impact if spec else 0
    d["confirmed"] = bool(d.get("confirmed"))
    return d


def get_catalysts(
    conn: sqlite3.Connection,
    hours: float = 48,
    min_score: float = 0,
    types: Iterable[str] | None = None,
    groups: Iterable[str] | None = None,
    direction: str | None = None,
    ticker: str | None = None,
    tickers: Iterable[str] | None = None,
    search: str | None = None,
    confirmed_only: bool = False,
    order: str = "score",
    limit: int = 100,
) -> list[dict[str, Any]]:
    where = ["published >= ?", "score >= ?"]
    params: list[Any] = [_iso(datetime.now(timezone.utc) - timedelta(hours=hours)), min_score]
    if types:
        vals = list(types)
        where.append(f"type IN ({','.join('?' * len(vals))})")
        params += vals
    if groups:
        vals = list(groups)
        where.append(f"catalyst_group IN ({','.join('?' * len(vals))})")
        params += vals
    if direction and direction != "all":
        where.append("direction = ?")
        params.append(direction)
    if ticker:
        where.append("ticker = ?")
        params.append(ticker.upper())
    if tickers:
        vals = [t.upper() for t in tickers]
        if vals:
            where.append(f"ticker IN ({','.join('?' * len(vals))})")
            params += vals
    if search:
        where.append("(headline LIKE ? OR ticker LIKE ? OR company LIKE ?)")
        like = f"%{search}%"
        params += [like, like, like]
    if confirmed_only:
        where.append("confirmed = 1")

    order_sql = {
        "score": "score DESC, published DESC",
        "time": "published DESC",
        "move": "ABS(COALESCE(change_pct, 0)) DESC, score DESC",
    }.get(order, "score DESC, published DESC")

    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        f"SELECT * FROM catalysts WHERE {' AND '.join(where)} ORDER BY {order_sql} LIMIT ?",
        [*params, limit],
    ).fetchall()
    return [_decode(r) for r in rows]


def get_catalyst(conn: sqlite3.Connection, catalyst_id: str) -> dict[str, Any] | None:
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM catalysts WHERE id = ?", (catalyst_id,)).fetchone()
    return _decode(row) if row else None


def catalyst_stats(conn: sqlite3.Connection, hours: float = 24) -> dict[str, Any]:
    cutoff = _iso(datetime.now(timezone.utc) - timedelta(hours=hours))
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT COUNT(*) total, "
        # 65 is the HIGH score band in the UI; keep the KPI and the badge in step.
        "SUM(CASE WHEN score >= 65 THEN 1 ELSE 0 END) high, "
        "SUM(CASE WHEN confirmed = 1 THEN 1 ELSE 0 END) confirmed, "
        "COUNT(DISTINCT ticker) tickers "
        "FROM catalysts WHERE published >= ?",
        (cutoff,),
    ).fetchone()
    by_group = {
        r["catalyst_group"]: r["n"]
        for r in conn.execute(
            "SELECT catalyst_group, COUNT(*) n FROM catalysts WHERE published >= ? "
            "GROUP BY catalyst_group ORDER BY n DESC",
            (cutoff,),
        )
    }
    return {
        "total": row["total"] or 0,
        "high_impact": row["high"] or 0,
        "confirmed": row["confirmed"] or 0,
        "tickers": row["tickers"] or 0,
        "by_group": by_group,
    }


def prune_stale_catalysts(
    conn: sqlite3.Connection, keep_ids: Iterable[str], hours: float
) -> int:
    """Drop catalysts in the scan window that the latest scan no longer produces.

    A catalyst's id encodes the ticker and type we assigned it, so re-resolving
    an event — the moment ticker extraction improves, say — mints a new id and
    the previous row would linger beside it as a duplicate. The board is a
    projection of the current analysis, not an accumulation of every past
    interpretation, so anything this scan re-derived from scratch and did not
    emit is removed.

    Only the window that was actually scanned is touched; older catalysts are
    left alone because this scan had no opportunity to re-derive them.
    """
    cutoff = _iso(datetime.now(timezone.utc) - timedelta(hours=hours))
    keep = list(dict.fromkeys(keep_ids))
    if not keep:
        deleted = conn.execute("DELETE FROM catalysts WHERE published >= ?", (cutoff,)).rowcount
        conn.commit()
        return deleted

    # A temp table keeps this correct past SQLite's host-parameter limit, which
    # a chunked NOT IN would silently violate by deleting another chunk's keeps.
    conn.execute("CREATE TEMP TABLE IF NOT EXISTS _keep_catalysts (id TEXT PRIMARY KEY)")
    conn.execute("DELETE FROM _keep_catalysts")
    conn.executemany("INSERT OR IGNORE INTO _keep_catalysts (id) VALUES (?)", [(k,) for k in keep])
    deleted = conn.execute(
        "DELETE FROM catalysts WHERE published >= ? "
        "AND id NOT IN (SELECT id FROM _keep_catalysts)",
        (cutoff,),
    ).rowcount
    conn.execute("DELETE FROM _keep_catalysts")
    conn.commit()
    return deleted


def prune_catalysts(conn: sqlite3.Connection, days: int = 7) -> int:
    cutoff = _iso(datetime.now(timezone.utc) - timedelta(days=days))
    n = conn.execute("DELETE FROM catalysts WHERE published < ?", (cutoff,)).rowcount
    conn.execute(
        "DELETE FROM catalyst_alerts WHERE catalyst_id NOT IN (SELECT id FROM catalysts)"
    )
    conn.commit()
    return n


# ── Alerting ─────────────────────────────────────────────────────────

def pending_alerts(
    conn: sqlite3.Connection,
    min_score: float = 70,
    watchlist: Iterable[str] | None = None,
    hours: float = 6,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """High-conviction catalysts not yet alerted on.

    A watchlist lowers the bar for its own tickers rather than excluding
    everything else — a 90-score buyout still matters if you don't own it.
    """
    watch = [t.upper() for t in (watchlist or [])]
    params: list[Any] = [_iso(datetime.now(timezone.utc) - timedelta(hours=hours))]
    # Columns are qualified: the alerts join makes a bare `score` ambiguous.
    clause = "c.score >= ?"
    params.append(min_score)
    if watch:
        clause = f"(c.score >= ? OR (c.ticker IN ({','.join('?' * len(watch))}) AND c.score >= ?))"
        params = params[:1] + [min_score] + watch + [min_score * 0.6]
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        f"SELECT c.* FROM catalysts c "
        f"LEFT JOIN catalyst_alerts a ON a.catalyst_id = c.id "
        f"WHERE a.catalyst_id IS NULL AND c.published >= ? AND {clause} "
        f"ORDER BY c.score DESC LIMIT ?",
        [*params, limit],
    ).fetchall()
    return [_decode(r) for r in rows]


def mark_alerted(conn: sqlite3.Connection, catalysts: Sequence[dict[str, Any]], channel: str = "") -> None:
    if not catalysts:
        return
    now = _iso(datetime.now(timezone.utc))
    conn.executemany(
        "INSERT OR REPLACE INTO catalyst_alerts (catalyst_id, sent_at, score, channel) VALUES (?,?,?,?)",
        [(c["id"], now, c.get("score", 0), channel) for c in catalysts],
    )
    conn.commit()

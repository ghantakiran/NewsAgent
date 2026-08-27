"""Database connection and operations.

Currently uses SQLite (same as the original app). Will be migrated to
PostgreSQL + SQLAlchemy async in Phase 1C.
"""

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..config import DB_DIR
from ..models.schemas import Category

DB_PATH = DB_DIR / "newsagent.db"


def get_connection() -> sqlite3.Connection:
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS articles (
            id TEXT PRIMARY KEY, title TEXT NOT NULL, url TEXT NOT NULL,
            source TEXT NOT NULL, published TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT 'general',
            tickers TEXT NOT NULL DEFAULT '[]',
            summary TEXT NOT NULL DEFAULT '', fetched_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS upgrades_downgrades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL, firm TEXT NOT NULL, action TEXT NOT NULL,
            old_rating TEXT DEFAULT '', new_rating TEXT DEFAULT '',
            price_target TEXT DEFAULT '', published TEXT NOT NULL,
            source_url TEXT DEFAULT '', source TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS custom_feeds (
            name TEXT PRIMARY KEY, url TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT 'general',
            enabled INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            hashed_password TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS user_watchlists (
            user_id INTEGER NOT NULL,
            ticker TEXT NOT NULL,
            PRIMARY KEY (user_id, ticker),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS user_settings (
            user_id INTEGER PRIMARY KEY,
            timezone TEXT NOT NULL DEFAULT 'America/New_York',
            notification_prefs TEXT NOT NULL DEFAULT '{}',
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS device_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            platform TEXT NOT NULL,
            token TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS discord_routes (
            category TEXT PRIMARY KEY,
            webhook_url TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            fail_count INTEGER NOT NULL DEFAULT 0,
            disabled INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS discord_sent (
            article_id TEXT PRIMARY KEY,
            category TEXT,
            sent_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS discord_watchlists (
            discord_user_id TEXT NOT NULL,
            ticker TEXT NOT NULL,
            PRIMARY KEY (discord_user_id, ticker)
        );
        CREATE TABLE IF NOT EXISTS alert_groups (
            group_id TEXT PRIMARY KEY,
            category TEXT NOT NULL DEFAULT 'general',
            ticker TEXT NOT NULL DEFAULT '',
            timeframe TEXT NOT NULL DEFAULT '',
            signal TEXT NOT NULL DEFAULT '',
            count INTEGER NOT NULL DEFAULT 1,
            first_seen TEXT NOT NULL,
            last_seen TEXT NOT NULL,
            latest TEXT NOT NULL DEFAULT '{}',
            history TEXT NOT NULL DEFAULT '[]'
        );
        CREATE INDEX IF NOT EXISTS idx_articles_published ON articles(published DESC);
        CREATE INDEX IF NOT EXISTS idx_articles_category ON articles(category);
        CREATE INDEX IF NOT EXISTS idx_ud_published ON upgrades_downgrades(published DESC);
        CREATE INDEX IF NOT EXISTS idx_discord_sent_at ON discord_sent(sent_at DESC);
        CREATE INDEX IF NOT EXISTS idx_alert_groups_last_seen ON alert_groups(last_seen DESC);
    """)
    conn.commit()


def _parse_dt(s: str) -> datetime:
    try:
        return datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return datetime.now(timezone.utc)


def prune_old_articles(conn: sqlite3.Connection, days: int = 7) -> None:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    conn.execute("DELETE FROM articles WHERE published < ?", (cutoff,))
    conn.execute("DELETE FROM upgrades_downgrades WHERE published < ?", (cutoff,))
    conn.commit()


def prune_discord_sent(conn: sqlite3.Connection, days: int = 14) -> None:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    conn.execute("DELETE FROM discord_sent WHERE sent_at < ?", (cutoff,))
    conn.commit()


def prune_old_alert_groups(conn: sqlite3.Connection, days: int = 3) -> None:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    conn.execute("DELETE FROM alert_groups WHERE last_seen < ?", (cutoff,))
    conn.commit()


def upsert_alert_group(conn: sqlite3.Connection, group: dict) -> None:
    """Insert or replace a coalesced alert-group snapshot, keyed by group_id."""
    conn.execute(
        """INSERT OR REPLACE INTO alert_groups
           (group_id,category,ticker,timeframe,signal,count,first_seen,last_seen,latest,history)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (
            group["group_id"], group.get("category", "general"), group.get("ticker", ""),
            group.get("timeframe", ""), group.get("signal", ""), int(group.get("count", 1)),
            group["first_seen"], group["last_seen"],
            json.dumps(group.get("latest", {})), json.dumps(group.get("history", [])),
        ),
    )
    conn.commit()


def get_recent_alert_groups(conn: sqlite3.Connection, limit: int = 100, hours: int = 24) -> list[dict]:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    rows = conn.execute(
        "SELECT * FROM alert_groups WHERE last_seen >= ? ORDER BY last_seen DESC LIMIT ?",
        (cutoff, limit),
    ).fetchall()
    return [
        {
            "group_id": r["group_id"], "category": r["category"], "ticker": r["ticker"],
            "timeframe": r["timeframe"], "signal": r["signal"], "count": r["count"],
            "first_seen": r["first_seen"], "last_seen": r["last_seen"],
            "latest": json.loads(r["latest"] or "{}"),
            "history": json.loads(r["history"] or "[]"),
        }
        for r in rows
    ]


def insert_article(conn: sqlite3.Connection, article: dict) -> bool:
    """Insert article dict, return True if new."""
    try:
        from datetime import datetime as dt
        published = article["published"]
        if isinstance(published, dt):
            published = published.isoformat()
        fetched_at = article.get("fetched_at", datetime.now(timezone.utc).isoformat())
        if isinstance(fetched_at, dt):
            fetched_at = fetched_at.isoformat()

        cur = conn.execute(
            "INSERT OR IGNORE INTO articles (id,title,url,source,published,category,tickers,summary,fetched_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (article["id"], article["title"], article["url"], article["source"],
             published, article["category"],
             json.dumps(article["tickers"]), article["summary"], fetched_at),
        )
        conn.commit()
        return cur.rowcount > 0
    except sqlite3.IntegrityError:
        return False


def insert_upgrade_downgrade(conn: sqlite3.Connection, ud: dict) -> None:
    published = ud["published"]
    if isinstance(published, datetime):
        pub_str = published.isoformat()
        pub_date = published.strftime("%Y-%m-%d")
    else:
        pub_str = published
        pub_date = published[:10]

    exists = conn.execute(
        "SELECT 1 FROM upgrades_downgrades WHERE ticker=? AND firm=? AND action=? AND published LIKE ?",
        (ud["ticker"], ud["firm"], ud["action"], pub_date + "%"),
    ).fetchone()
    if exists:
        return
    conn.execute(
        "INSERT INTO upgrades_downgrades (ticker,firm,action,old_rating,new_rating,price_target,published,source_url,source) VALUES (?,?,?,?,?,?,?,?,?)",
        (ud["ticker"], ud["firm"], ud["action"], ud["old_rating"], ud["new_rating"],
         ud["price_target"], pub_str, ud["source_url"], ud["source"]),
    )
    conn.commit()


def get_articles(conn, limit=100, category=None, ticker=None, search=None, hours=48) -> list[dict]:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    q, p = "SELECT * FROM articles WHERE published >= ?", [cutoff]
    if category and category != "all":
        q += " AND category = ?"
        p.append(category)
    if ticker:
        q += " AND tickers LIKE ?"
        p.append(f'%"{ticker}"%')
    if search:
        s = search.strip()
        q += " AND (title LIKE ? OR summary LIKE ? OR tickers LIKE ? COLLATE NOCASE)"
        p.extend([f"%{s}%", f"%{s}%", f'%"{s.upper()}"%'])
    q += " ORDER BY published DESC LIMIT ?"
    p.append(limit)
    rows = conn.execute(q, p).fetchall()
    return [
        {
            "id": r["id"], "title": r["title"], "url": r["url"], "source": r["source"],
            "published": _parse_dt(r["published"]),
            "category": r["category"] if r["category"] in Category._value2member_map_ else "general",
            "tickers": json.loads(r["tickers"]), "summary": r["summary"],
            "fetched_at": _parse_dt(r["fetched_at"]),
        }
        for r in rows
    ]


def get_upgrades_downgrades(conn, limit=100, ticker=None, search=None, hours=48) -> list[dict]:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    q, p = "SELECT * FROM upgrades_downgrades WHERE published >= ?", [cutoff]
    if ticker:
        q += " AND ticker = ?"
        p.append(ticker.upper())
    if search:
        s = search.strip()
        q += " AND (ticker LIKE ? OR firm LIKE ? OR action LIKE ? COLLATE NOCASE)"
        p.extend([f"%{s}%", f"%{s}%", f"%{s}%"])
    q += " ORDER BY published DESC LIMIT ?"
    p.append(limit)
    return [
        {
            "ticker": r["ticker"], "firm": r["firm"], "action": r["action"],
            "old_rating": r["old_rating"], "new_rating": r["new_rating"],
            "price_target": r["price_target"], "published": _parse_dt(r["published"]),
            "source_url": r["source_url"], "source": r["source"],
        }
        for r in conn.execute(q, p).fetchall()
    ]


def reprocess_upgrades_downgrades(conn: sqlite3.Connection) -> int:
    from ..services.ud_service import parse_upgrade_downgrade
    conn.execute("DELETE FROM upgrades_downgrades")
    conn.commit()
    articles = get_articles(conn, limit=1000, category="upgrade")
    articles += get_articles(conn, limit=1000, category="downgrade")
    count = 0
    for a in articles:
        ud = parse_upgrade_downgrade(
            a["title"], a["summary"], a["tickers"],
            a["published"], a["url"], a["source"],
        )
        if ud and ud["ticker"] != "N/A":
            insert_upgrade_downgrade(conn, ud)
            count += 1
    all_arts = get_articles(conn, limit=2000)
    for a in all_arts:
        if a["category"] in ("upgrade", "downgrade"):
            continue
        ud = parse_upgrade_downgrade(
            a["title"], a["summary"], a["tickers"],
            a["published"], a["url"], a["source"],
        )
        if ud and ud["ticker"] != "N/A":
            insert_upgrade_downgrade(conn, ud)
            count += 1
    return count


def get_article_count(conn) -> int:
    return conn.execute("SELECT COUNT(*) as c FROM articles").fetchone()["c"]


def get_source_counts(conn) -> dict[str, int]:
    return {
        r["source"]: r["c"]
        for r in conn.execute("SELECT source, COUNT(*) as c FROM articles GROUP BY source ORDER BY c DESC").fetchall()
    }


def get_articles_by_ticker(conn, limit_per_ticker: int = 10) -> dict[str, list[dict]]:
    from ..services.parser_service import TICKER_EXCLUSIONS
    rows = conn.execute(
        "SELECT * FROM articles WHERE tickers != '[]' ORDER BY published DESC LIMIT 2000"
    ).fetchall()
    by_ticker: dict[str, list[dict]] = {}
    for r in rows:
        art = {
            "id": r["id"], "title": r["title"], "url": r["url"], "source": r["source"],
            "published": _parse_dt(r["published"]),
            "category": r["category"] if r["category"] in Category._value2member_map_ else "general",
            "tickers": json.loads(r["tickers"]), "summary": r["summary"],
            "fetched_at": _parse_dt(r["fetched_at"]),
        }
        for t in art["tickers"][:3]:
            if t not in TICKER_EXCLUSIONS:
                if t not in by_ticker:
                    by_ticker[t] = []
                if len(by_ticker[t]) < limit_per_ticker:
                    by_ticker[t].append(art)
    return dict(sorted(by_ticker.items(), key=lambda x: -len(x[1])))


def get_all_tickers(conn) -> list[str]:
    from ..services.parser_service import TICKER_EXCLUSIONS
    rows = conn.execute(
        "SELECT tickers FROM articles WHERE tickers != '[]' ORDER BY published DESC LIMIT 5000"
    ).fetchall()
    counts: dict[str, int] = {}
    for r in rows:
        for t in json.loads(r["tickers"]):
            if t not in TICKER_EXCLUSIONS:
                counts[t] = counts.get(t, 0) + 1
    return sorted(counts.keys(), key=lambda t: -counts[t])


# Custom feeds CRUD

def save_custom_feed(conn, name, url, category, enabled):
    conn.execute("INSERT OR REPLACE INTO custom_feeds (name,url,category,enabled) VALUES (?,?,?,?)",
                 (name, url, category, int(enabled)))
    conn.commit()


def get_custom_feeds(conn) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT * FROM custom_feeds").fetchall()]


def delete_custom_feed(conn, name):
    conn.execute("DELETE FROM custom_feeds WHERE name = ?", (name,))
    conn.commit()


def toggle_custom_feed(conn, name, enabled):
    conn.execute("UPDATE custom_feeds SET enabled = ? WHERE name = ?", (int(enabled), name))
    conn.commit()


# User CRUD

def create_user(conn, email: str, hashed_password: str) -> int:
    cur = conn.execute(
        "INSERT INTO users (email, hashed_password) VALUES (?, ?)",
        (email, hashed_password),
    )
    conn.commit()
    return cur.lastrowid


def get_user_by_email(conn, email: str) -> dict | None:
    row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    return dict(row) if row else None


def get_user_by_id(conn, user_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


def get_watchlist(conn, user_id: int) -> list[str]:
    rows = conn.execute("SELECT ticker FROM user_watchlists WHERE user_id = ?", (user_id,)).fetchall()
    return [r["ticker"] for r in rows]


def set_watchlist(conn, user_id: int, tickers: list[str]) -> None:
    conn.execute("DELETE FROM user_watchlists WHERE user_id = ?", (user_id,))
    for t in tickers:
        conn.execute("INSERT INTO user_watchlists (user_id, ticker) VALUES (?, ?)", (user_id, t.upper()))
    conn.commit()


def get_user_settings(conn, user_id: int) -> dict:
    row = conn.execute("SELECT * FROM user_settings WHERE user_id = ?", (user_id,)).fetchone()
    if row:
        return {"timezone": row["timezone"], "notification_prefs": json.loads(row["notification_prefs"])}
    return {"timezone": "America/New_York", "notification_prefs": {}}


def update_user_settings(conn, user_id: int, tz: str | None = None, notif_prefs: dict | None = None) -> None:
    existing = get_user_settings(conn, user_id)
    tz = tz or existing["timezone"]
    prefs = json.dumps(notif_prefs if notif_prefs is not None else existing["notification_prefs"])
    conn.execute(
        "INSERT OR REPLACE INTO user_settings (user_id, timezone, notification_prefs) VALUES (?, ?, ?)",
        (user_id, tz, prefs),
    )
    conn.commit()


# Discord routes + sent-log (outbound webhook push)

def get_discord_routes(conn) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT * FROM discord_routes").fetchall()]


def get_discord_route(conn, category: str) -> dict | None:
    row = conn.execute("SELECT * FROM discord_routes WHERE category = ?", (category,)).fetchone()
    return dict(row) if row else None


def save_discord_route(conn, category: str, webhook_url: str, enabled: bool = True) -> None:
    """Upsert a route; resets fail_count/disabled so a re-saved URL is re-enabled."""
    conn.execute(
        "INSERT OR REPLACE INTO discord_routes (category, webhook_url, enabled, fail_count, disabled, updated_at) "
        "VALUES (?, ?, ?, 0, 0, ?)",
        (category, webhook_url.strip(), int(enabled), datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()


def set_discord_route_enabled(conn, category: str, enabled: bool) -> None:
    conn.execute("UPDATE discord_routes SET enabled = ? WHERE category = ?", (int(enabled), category))
    conn.commit()


def delete_discord_route(conn, category: str) -> None:
    conn.execute("DELETE FROM discord_routes WHERE category = ?", (category,))
    conn.commit()


def bump_discord_route_failure(conn, category: str, max_failures: int) -> int:
    """Increment a route's consecutive-failure counter; auto-disable past the threshold.

    Returns the new fail_count. No-op (returns 0) for env-var-only routes with no DB row.
    """
    conn.execute("UPDATE discord_routes SET fail_count = fail_count + 1 WHERE category = ?", (category,))
    conn.commit()
    row = conn.execute("SELECT fail_count FROM discord_routes WHERE category = ?", (category,)).fetchone()
    fails = row["fail_count"] if row else 0
    if fails >= max_failures:
        conn.execute("UPDATE discord_routes SET disabled = 1 WHERE category = ?", (category,))
        conn.commit()
    return fails


def reset_discord_route_failure(conn, category: str) -> None:
    conn.execute("UPDATE discord_routes SET fail_count = 0, disabled = 0 WHERE category = ? AND fail_count > 0", (category,))
    conn.commit()


def has_sent_to_discord(conn, article_id: str) -> bool:
    return conn.execute("SELECT 1 FROM discord_sent WHERE article_id = ?", (article_id,)).fetchone() is not None


def log_discord_sent(conn, article_id: str, category: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO discord_sent (article_id, category, sent_at) VALUES (?, ?, ?)",
        (article_id, category, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()


# Discord per-user watchlists (driven by /watchlist slash command)

def add_discord_watch(conn, discord_user_id: str, ticker: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO discord_watchlists (discord_user_id, ticker) VALUES (?, ?)",
        (discord_user_id, ticker.upper()),
    )
    conn.commit()


def remove_discord_watch(conn, discord_user_id: str, ticker: str) -> None:
    conn.execute(
        "DELETE FROM discord_watchlists WHERE discord_user_id = ? AND ticker = ?",
        (discord_user_id, ticker.upper()),
    )
    conn.commit()


def get_discord_watch(conn, discord_user_id: str) -> list[str]:
    rows = conn.execute(
        "SELECT ticker FROM discord_watchlists WHERE discord_user_id = ? ORDER BY ticker",
        (discord_user_id,),
    ).fetchall()
    return [r["ticker"] for r in rows]

"""SQLite cache layer for articles."""

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .models import Article, Category, UpgradeDowngrade

DB_DIR = Path(__file__).parent.parent.parent / "data"
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
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            url TEXT NOT NULL,
            source TEXT NOT NULL,
            published TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT 'general',
            tickers TEXT NOT NULL DEFAULT '[]',
            summary TEXT NOT NULL DEFAULT '',
            fetched_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS upgrades_downgrades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            firm TEXT NOT NULL,
            action TEXT NOT NULL,
            old_rating TEXT DEFAULT '',
            new_rating TEXT DEFAULT '',
            price_target TEXT DEFAULT '',
            published TEXT NOT NULL,
            source_url TEXT DEFAULT '',
            source TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS custom_feeds (
            name TEXT PRIMARY KEY,
            url TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT 'general',
            enabled INTEGER NOT NULL DEFAULT 1
        );

        CREATE INDEX IF NOT EXISTS idx_articles_published ON articles(published DESC);
        CREATE INDEX IF NOT EXISTS idx_articles_category ON articles(category);
        CREATE INDEX IF NOT EXISTS idx_ud_published ON upgrades_downgrades(published DESC);
    """)
    conn.commit()


def prune_old_articles(conn: sqlite3.Connection, days: int = 7) -> int:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    cursor = conn.execute("DELETE FROM articles WHERE published < ?", (cutoff,))
    conn.execute("DELETE FROM upgrades_downgrades WHERE published < ?", (cutoff,))
    conn.commit()
    return cursor.rowcount


def insert_article(conn: sqlite3.Connection, article: Article) -> bool:
    """Insert article, return True if new (not duplicate)."""
    try:
        cursor = conn.execute(
            """INSERT OR IGNORE INTO articles
               (id, title, url, source, published, category, tickers, summary, fetched_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                article.id,
                article.title,
                article.url,
                article.source,
                article.published.isoformat(),
                article.category.value,
                json.dumps(article.tickers),
                article.summary,
                article.fetched_at.isoformat(),
            ),
        )
        conn.commit()
        return cursor.rowcount > 0
    except sqlite3.IntegrityError:
        return False


def insert_upgrade_downgrade(conn: sqlite3.Connection, ud: UpgradeDowngrade) -> None:
    conn.execute(
        """INSERT INTO upgrades_downgrades
           (ticker, firm, action, old_rating, new_rating, price_target, published, source_url, source)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            ud.ticker, ud.firm, ud.action, ud.old_rating, ud.new_rating,
            ud.price_target, ud.published.isoformat(), ud.source_url, ud.source,
        ),
    )
    conn.commit()


def get_articles(
    conn: sqlite3.Connection,
    limit: int = 100,
    category: str | None = None,
    ticker: str | None = None,
    search: str | None = None,
) -> list[Article]:
    query = "SELECT * FROM articles WHERE 1=1"
    params: list = []

    if category and category != "all":
        query += " AND category = ?"
        params.append(category)
    if ticker:
        query += " AND tickers LIKE ?"
        params.append(f'%"{ticker}"%')
    if search:
        query += " AND (title LIKE ? OR summary LIKE ?)"
        params.extend([f"%{search}%", f"%{search}%"])

    query += " ORDER BY published DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(query, params).fetchall()
    articles = []
    for row in rows:
        try:
            published = datetime.fromisoformat(row["published"])
        except (ValueError, TypeError):
            published = datetime.now(timezone.utc)
        try:
            fetched_at = datetime.fromisoformat(row["fetched_at"])
        except (ValueError, TypeError):
            fetched_at = datetime.now(timezone.utc)

        articles.append(Article(
            id=row["id"],
            title=row["title"],
            url=row["url"],
            source=row["source"],
            published=published,
            category=Category(row["category"]) if row["category"] in Category._value2member_map_ else Category.GENERAL,
            tickers=json.loads(row["tickers"]),
            summary=row["summary"],
            fetched_at=fetched_at,
        ))
    return articles


def get_upgrades_downgrades(
    conn: sqlite3.Connection,
    limit: int = 100,
    ticker: str | None = None,
) -> list[UpgradeDowngrade]:
    query = "SELECT * FROM upgrades_downgrades WHERE 1=1"
    params: list = []
    if ticker:
        query += " AND ticker = ?"
        params.append(ticker.upper())
    query += " ORDER BY published DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(query, params).fetchall()
    results = []
    for row in rows:
        try:
            published = datetime.fromisoformat(row["published"])
        except (ValueError, TypeError):
            published = datetime.now(timezone.utc)
        results.append(UpgradeDowngrade(
            ticker=row["ticker"],
            firm=row["firm"],
            action=row["action"],
            old_rating=row["old_rating"],
            new_rating=row["new_rating"],
            price_target=row["price_target"],
            published=published,
            source_url=row["source_url"],
            source=row["source"],
        ))
    return results


def save_custom_feed(conn: sqlite3.Connection, name: str, url: str, category: str, enabled: bool) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO custom_feeds (name, url, category, enabled) VALUES (?, ?, ?, ?)",
        (name, url, category, int(enabled)),
    )
    conn.commit()


def get_custom_feeds(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT * FROM custom_feeds").fetchall()
    return [dict(row) for row in rows]


def delete_custom_feed(conn: sqlite3.Connection, name: str) -> None:
    conn.execute("DELETE FROM custom_feeds WHERE name = ?", (name,))
    conn.commit()


def toggle_custom_feed(conn: sqlite3.Connection, name: str, enabled: bool) -> None:
    conn.execute("UPDATE custom_feeds SET enabled = ? WHERE name = ?", (int(enabled), name))
    conn.commit()


def get_article_count(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COUNT(*) as cnt FROM articles").fetchone()
    return row["cnt"] if row else 0


def get_source_counts(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute(
        "SELECT source, COUNT(*) as cnt FROM articles GROUP BY source ORDER BY cnt DESC"
    ).fetchall()
    return {row["source"]: row["cnt"] for row in rows}

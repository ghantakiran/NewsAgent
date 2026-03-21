"""Feed management — load defaults, manage custom feeds."""

from pathlib import Path

import toml

from .database import (
    delete_custom_feed,
    get_connection,
    get_custom_feeds,
    init_db,
    save_custom_feed,
    toggle_custom_feed,
)
from .models import Feed

CONFIG_DIR = Path(__file__).parent.parent.parent / "config"


def load_default_feeds() -> list[Feed]:
    """Load feeds from config/default_feeds.toml."""
    config_path = CONFIG_DIR / "default_feeds.toml"
    if not config_path.exists():
        return []

    data = toml.load(str(config_path))
    feeds = []
    for f in data.get("feeds", []):
        feeds.append(Feed(
            name=f["name"],
            url=f["url"],
            category=f.get("category", "general"),
            enabled=f.get("enabled", True),
        ))
    return feeds


def load_custom_feeds() -> list[Feed]:
    """Load user-added feeds from database."""
    conn = get_connection()
    init_db(conn)
    rows = get_custom_feeds(conn)
    conn.close()
    feeds = []
    for row in rows:
        feeds.append(Feed(
            name=row["name"],
            url=row["url"],
            category=row.get("category", "general"),
            enabled=bool(row.get("enabled", 1)),
        ))
    return feeds


def load_all_feeds() -> list[Feed]:
    """Load both default and custom feeds."""
    return load_default_feeds() + load_custom_feeds()


def add_custom_feed(name: str, url: str, category: str = "general") -> None:
    conn = get_connection()
    init_db(conn)
    save_custom_feed(conn, name, url, category, True)
    conn.close()


def remove_custom_feed(name: str) -> None:
    conn = get_connection()
    init_db(conn)
    delete_custom_feed(conn, name)
    conn.close()


def toggle_feed(name: str, enabled: bool) -> None:
    conn = get_connection()
    init_db(conn)
    toggle_custom_feed(conn, name, enabled)
    conn.close()


def load_settings() -> dict:
    """Load settings from config/settings.toml."""
    settings_path = CONFIG_DIR / "settings.toml"
    if not settings_path.exists():
        return {"general": {"refresh_interval": 30, "max_articles": 500, "prune_after_days": 7}}
    return toml.load(str(settings_path))

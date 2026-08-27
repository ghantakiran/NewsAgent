"""Grok-backed endpoints: live X/web search for the API.

Thin wrapper over `newsagent.catalysts.grok` that adds the database side —
storing what Grok finds and re-ranking the board afterwards — so the router
stays about HTTP.
"""

from __future__ import annotations

import logging
import sqlite3

from ..core.database import insert_article
from .catalyst_service import refresh_catalysts
from .parser_service import parse_entry

logger = logging.getLogger(__name__)

# catalyst_service puts src/ on the path before these resolve.
from newsagent.catalysts import grok  # noqa: E402

__all__ = ["explain_catalyst", "grok_status", "squawk_now"]


def grok_status() -> dict:
    return {
        "available": grok.available(),
        "model": grok.DEFAULT_MODEL if grok.available() else None,
        "reason": None if grok.available() else "XAI_API_KEY is not set",
    }


def squawk_now(conn: sqlite3.Connection, minutes: int = 30) -> tuple[int, int]:
    """Store Grok's findings, then re-rank. Returns (stored, catalysts_detected)."""
    if not grok.available():
        return 0, 0
    items = grok.fetch_squawk(minutes=minutes, respect_throttle=False)
    stored = 0
    for item in items:
        entry = {
            "title": item.title, "link": item.url, "summary": item.summary,
            "published": item.published.isoformat(),
        }
        try:
            if insert_article(conn, parse_entry(entry, "Grok Squawk", "general")):
                stored += 1
        except Exception as exc:
            logger.debug("could not store grok item: %s", exc)
    detected = 0
    if stored:
        detected, _ = refresh_catalysts(conn, with_quotes=False)
    return stored, detected


def explain_catalyst(catalyst: dict) -> dict:
    """Why is this name moving? Grok reads X and the web live to answer."""
    ticker = catalyst.get("ticker") or ""
    if not ticker:
        return {"available": False, "reason": "Catalyst has no ticker to explain"}
    if not grok.available():
        return {"available": False, "reason": "XAI_API_KEY is not set"}
    answer = grok.explain_move(ticker, catalyst.get("change_pct") or 0.0, respect_throttle=False)
    return {
        "available": answer.ok,
        "ticker": ticker,
        "explanation": answer.text,
        "citations": answer.citations,
        "model": answer.model,
        "reason": answer.error or None,
    }

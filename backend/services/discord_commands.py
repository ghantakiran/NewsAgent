"""Discord slash-command handling via the signed HTTP Interactions endpoint.

No gateway bot / persistent connection: Discord POSTs each interaction to
``POST /api/v1/discord/interactions``. We verify the Ed25519 signature, answer
the PING handshake, and reply to commands inline (all handlers are quick DB
reads, well under Discord's 3-second response window).

Commands: /latest, /ud, /watchlist (add|remove|list), /help. Replies are
ephemeral (flags=64) so they only show to the invoking user.
"""
from __future__ import annotations

import logging

from ..core.database import (
    add_discord_watch,
    get_articles,
    get_discord_watch,
    get_upgrades_downgrades,
    remove_discord_watch,
)
from .discord_service import build_embed

logger = logging.getLogger(__name__)

try:
    from nacl.exceptions import BadSignatureError
    from nacl.signing import VerifyKey
    _HAS_NACL = True
except ImportError:  # pragma: no cover
    _HAS_NACL = False

# Interaction + response type constants (Discord API)
PING = 1
APPLICATION_COMMAND = 2
PONG = 1
CHANNEL_MESSAGE = 4
EPHEMERAL = 64

CATEGORIES = [
    "general", "earnings", "upgrade", "downgrade", "macro", "fda",
    "m&a", "ipo", "insider", "dividend", "filing", "crypto", "tech",
]


def verify_signature(public_key: str, signature: str, timestamp: str, body: bytes) -> bool:
    """Verify an interaction request's Ed25519 signature. False on any failure."""
    if not _HAS_NACL or not public_key or not signature or not timestamp:
        return False
    try:
        VerifyKey(bytes.fromhex(public_key)).verify(timestamp.encode() + body, bytes.fromhex(signature))
        return True
    except (BadSignatureError, ValueError, Exception):  # noqa: BLE001 - never trust bad input
        return False


def handle_interaction(payload: dict, conn) -> dict:
    """Route a verified interaction payload to a response dict."""
    itype = payload.get("type")
    if itype == PING:
        return {"type": PONG}
    if itype != APPLICATION_COMMAND:
        return _ephemeral("Unsupported interaction.")

    data = payload.get("data", {})
    name = data.get("name")
    try:
        if name == "latest":
            return _cmd_latest(data, conn)
        if name == "ud":
            return _cmd_ud(data, conn)
        if name == "watchlist":
            return _cmd_watchlist(data, conn, _user_id(payload))
        if name == "help":
            return _cmd_help()
    except Exception as e:  # pragma: no cover - never 500 a Discord interaction
        logger.warning(f"Discord command '{name}' failed: {e}")
        return _ephemeral("Something went wrong handling that command.")
    return _ephemeral("Unknown command.")


# ── Command handlers ─────────────────────────────────────────────────────────

def _cmd_latest(data: dict, conn) -> dict:
    o = _opts(data)
    category = o.get("category")
    ticker = (o.get("ticker") or "").upper().strip() or None
    arts = get_articles(conn, limit=6, category=category, ticker=ticker, hours=48)
    if not arts:
        return _ephemeral("No matching articles in the last 48h.")
    embeds = [build_embed(a) for a in arts[:6]]
    label = ticker or (category or "latest")
    return _ephemeral(f"**Latest — {label}**", embeds)


def _cmd_ud(data: dict, conn) -> dict:
    o = _opts(data)
    ticker = (o.get("ticker") or "").upper().strip() or None
    uds = get_upgrades_downgrades(conn, limit=10, ticker=ticker, hours=72)
    if not uds:
        return _ephemeral("No upgrades/downgrades in the last 72h.")
    lines = []
    for u in uds[:10]:
        arrow = "📈" if u["action"] == "upgrade" else ("📉" if u["action"] == "downgrade" else "•")
        pt = f" · PT {u['price_target']}" if u.get("price_target") else ""
        rating = f" ({u['old_rating']}→{u['new_rating']})" if u.get("new_rating") else ""
        lines.append(f"{arrow} **{u['ticker']}** {u['action']} — {u['firm']}{rating}{pt}")
    return _ephemeral("\n".join(lines)[:1900])


def _cmd_watchlist(data: dict, conn, user_id: str | None) -> dict:
    if not user_id:
        return _ephemeral("Couldn't identify your Discord user.")
    sub = (data.get("options") or [{}])[0]
    action = sub.get("name")
    so = {o["name"]: o.get("value") for o in (sub.get("options") or [])}
    ticker = (so.get("ticker") or "").upper().strip()
    if action == "add":
        if not ticker:
            return _ephemeral("Provide a ticker, e.g. `/watchlist add AAPL`.")
        add_discord_watch(conn, user_id, ticker)
        return _ephemeral(f"✅ Added **{ticker}** to your watchlist.")
    if action == "remove":
        if not ticker:
            return _ephemeral("Provide a ticker to remove.")
        remove_discord_watch(conn, user_id, ticker)
        return _ephemeral(f"🗑️ Removed **{ticker}** from your watchlist.")
    if action == "list":
        wl = get_discord_watch(conn, user_id)
        return _ephemeral("**Your watchlist:** " + (", ".join(f"`{t}`" for t in wl) if wl else "_empty_"))
    return _ephemeral("Unknown watchlist action.")


def _cmd_help() -> dict:
    return _ephemeral(
        "**NewsAgent commands**\n"
        "• `/latest [category] [ticker]` — recent headlines\n"
        "• `/ud [ticker]` — recent upgrades & downgrades\n"
        "• `/watchlist add|remove|list [ticker]` — manage your tickers\n"
        "• `/help` — this message"
    )


# ── Helpers ──────────────────────────────────────────────────────────────────

def _opts(data: dict) -> dict:
    return {o["name"]: o.get("value") for o in (data.get("options") or [])}


def _user_id(payload: dict) -> str | None:
    member = payload.get("member") or {}
    user = member.get("user") or payload.get("user") or {}
    return user.get("id")


def _ephemeral(content: str | None = None, embeds: list[dict] | None = None) -> dict:
    inner: dict = {"flags": EPHEMERAL}
    if content:
        inner["content"] = content
    if embeds:
        inner["embeds"] = embeds[:10]
    return {"type": CHANNEL_MESSAGE, "data": inner}

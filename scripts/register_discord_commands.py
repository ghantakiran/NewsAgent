#!/usr/bin/env python3
"""Register (bulk-overwrite) NewsAgent's Discord slash commands.

One-time / on-change setup. Requires env vars:
  DISCORD_APP_ID     — Application ID (Developer Portal → General Information)
  DISCORD_BOT_TOKEN  — Bot token (Developer Portal → Bot)
  DISCORD_GUILD_ID   — optional; if set, registers to that guild (instant).
                       Omit for global commands (~1h to propagate).

Usage:
    python scripts/register_discord_commands.py

Set the interactions endpoint URL in the Developer Portal to:
    https://<your-backend>/api/v1/discord/interactions
(Discord will probe it with a signed PING — the backend must be running and
 DISCORD_PUBLIC_KEY must be set so verification passes.)
"""
import os
import sys

import httpx

API = "https://discord.com/api/v10"

STRING = 3
SUB_COMMAND = 1

CATEGORIES = [
    "general", "earnings", "upgrade", "downgrade", "macro", "fda",
    "m&a", "ipo", "insider", "dividend", "filing", "crypto", "tech",
]

COMMANDS = [
    {
        "name": "latest",
        "description": "Show the latest NewsAgent headlines",
        "options": [
            {
                "type": STRING, "name": "category", "description": "Filter by category",
                "required": False,
                "choices": [{"name": c, "value": c} for c in CATEGORIES],
            },
            {"type": STRING, "name": "ticker", "description": "Filter by ticker (e.g. AAPL)", "required": False},
        ],
    },
    {
        "name": "ud",
        "description": "Recent analyst upgrades & downgrades",
        "options": [
            {"type": STRING, "name": "ticker", "description": "Filter by ticker", "required": False},
        ],
    },
    {
        "name": "watchlist",
        "description": "Manage your personal watchlist",
        "options": [
            {"type": SUB_COMMAND, "name": "add", "description": "Add a ticker",
             "options": [{"type": STRING, "name": "ticker", "description": "Ticker", "required": True}]},
            {"type": SUB_COMMAND, "name": "remove", "description": "Remove a ticker",
             "options": [{"type": STRING, "name": "ticker", "description": "Ticker", "required": True}]},
            {"type": SUB_COMMAND, "name": "list", "description": "List your tickers"},
        ],
    },
    {"name": "help", "description": "List NewsAgent commands"},
]


def main() -> int:
    app_id = os.getenv("DISCORD_APP_ID", "").strip()
    token = os.getenv("DISCORD_BOT_TOKEN", "").strip()
    guild_id = os.getenv("DISCORD_GUILD_ID", "").strip()
    if not app_id or not token:
        print("ERROR: set DISCORD_APP_ID and DISCORD_BOT_TOKEN", file=sys.stderr)
        return 1

    if guild_id:
        url = f"{API}/applications/{app_id}/guilds/{guild_id}/commands"
        scope = f"guild {guild_id} (instant)"
    else:
        url = f"{API}/applications/{app_id}/commands"
        scope = "global (~1h to propagate)"

    headers = {"Authorization": f"Bot {token}", "Content-Type": "application/json"}
    # PUT = bulk overwrite (idempotent): replaces the full command set.
    resp = httpx.put(url, headers=headers, json=COMMANDS, timeout=30)
    if resp.status_code in (200, 201):
        print(f"Registered {len(resp.json())} commands [{scope}].")
        return 0
    print(f"ERROR {resp.status_code}: {resp.text}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

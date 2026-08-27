"""Application configuration loaded from environment variables."""

import os
from pathlib import Path

# Paths
ROOT = Path(__file__).parent.parent
CONFIG_DIR = ROOT / "config"
DB_DIR = ROOT / "data"

# Database
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DB_DIR / 'newsagent.db'}")

# JWT Auth
JWT_SECRET = os.getenv("JWT_SECRET", "dev-secret-change-in-production")
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60
REFRESH_TOKEN_EXPIRE_DAYS = 30

# CORS
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "*").split(",")

# Feed settings (defaults, overridden by config/settings.toml)
DEFAULT_REFRESH_INTERVAL = 15
DEFAULT_MAX_ARTICLES = 500
DEFAULT_PRUNE_AFTER_DAYS = 7

# Firebase (push notifications)
FIREBASE_CREDENTIALS_PATH = os.getenv("FIREBASE_CREDENTIALS_PATH", "")

# Discord outbound webhooks (category-routed news push)
# Routes are normally configured per-category in the discord_routes table via the
# Streamlit "Discord" page. DISCORD_WEBHOOK_<CATEGORY> env vars are an optional
# fallback (e.g. DISCORD_WEBHOOK_GENERAL, DISCORD_WEBHOOK_UPGRADE, DISCORD_WEBHOOK_MA).
DISCORD_ENABLED = os.getenv("DISCORD_ENABLED", "true").lower() in ("1", "true", "yes")
DISCORD_USERNAME = os.getenv("DISCORD_USERNAME", "NewsAgent Squawk")
DISCORD_AVATAR_URL = os.getenv("DISCORD_AVATAR_URL", "")
DISCORD_THROTTLE_SECONDS = float(os.getenv("DISCORD_THROTTLE_SECONDS", "2.5"))
DISCORD_MAX_ROUTE_FAILURES = int(os.getenv("DISCORD_MAX_ROUTE_FAILURES", "5"))
DISCORD_MAX_AGE_MINUTES = int(os.getenv("DISCORD_MAX_AGE_MINUTES", "30"))
DISCORD_SENT_RETENTION_DAYS = int(os.getenv("DISCORD_SENT_RETENTION_DAYS", "14"))

# Discord slash commands (Phase 2 - signed HTTP interactions endpoint, no gateway bot)
# DISCORD_PUBLIC_KEY: app's Ed25519 public key (Discord Developer Portal → General Information).
# DISCORD_APP_ID + DISCORD_BOT_TOKEN: needed only to REGISTER commands (scripts/register_discord_commands.py).
# DISCORD_GUILD_ID: optional; if set, commands register to that guild (instant) instead of globally (~1h).
DISCORD_PUBLIC_KEY = os.getenv("DISCORD_PUBLIC_KEY", "")
DISCORD_APP_ID = os.getenv("DISCORD_APP_ID", "")
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "")
DISCORD_GUILD_ID = os.getenv("DISCORD_GUILD_ID", "")

# TradingView inbound alert webhook.
# TradingView's free tier can't send custom headers, so the shared secret is
# passed as a ?token= query param (or a "token" field in the JSON body). Set
# TRADINGVIEW_WEBHOOK_TOKEN to a long random string and point your TradingView
# alert webhook URL at: https://<host>/api/v1/webhook/tradingview?token=<secret>
TRADINGVIEW_WEBHOOK_TOKEN = os.getenv("TRADINGVIEW_WEBHOOK_TOKEN", "")

# Alert coalescing: a burst ("episode") of alerts sharing the same group key
# within COALESCE_WINDOW_SECONDS collapses into one updating card on the
# dashboard instead of N separate rows. Group key fields are comma-separated
# and drawn from the normalized alert (category, ticker, timeframe, signal).
COALESCE_WINDOW_SECONDS = int(os.getenv("COALESCE_WINDOW_SECONDS", "60"))
COALESCE_GROUP_KEY = os.getenv("COALESCE_GROUP_KEY", "category,ticker")
ALERT_HISTORY_LIMIT = int(os.getenv("ALERT_HISTORY_LIMIT", "20"))
ALERT_PRUNE_AFTER_DAYS = int(os.getenv("ALERT_PRUNE_AFTER_DAYS", "3"))

# ── Catalyst board ───────────────────────────────────────────────────────────
# Only catalysts scoring at or above this get a Discord ping. 70 is roughly the
# "drop what you're doing" line: buyouts, FDA decisions, dilution, halts.
CATALYST_ALERT_MIN_SCORE = float(os.getenv("CATALYST_ALERT_MIN_SCORE", "70"))
CATALYST_ALERT_MAX_AGE_HOURS = float(os.getenv("CATALYST_ALERT_MAX_AGE_HOURS", "6"))
CATALYST_ALERTS_ENABLED = os.getenv("CATALYST_ALERTS_ENABLED", "true").lower() in ("1", "true", "yes")
# Forward inbound TradingView alerts on to the existing per-category Discord
# routes too, so TradingView's direct Discord webhook can be retired later.
TRADINGVIEW_FORWARD_DISCORD = os.getenv("TRADINGVIEW_FORWARD_DISCORD", "false").lower() in ("1", "true", "yes")

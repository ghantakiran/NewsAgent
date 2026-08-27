"""Push notification service using Firebase Cloud Messaging.

Checks new articles against user watchlists and sends push notifications.
For now, implements the logic without requiring firebase-admin to be installed,
so it can be enabled when Firebase is configured.
"""

import json
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Notification categories and their templates
NOTIFICATION_CATEGORIES = {
    "watchlist": "📊 {ticker}: {title}",
    "upgrade": "📈 {ticker}: Upgraded — {title}",
    "downgrade": "📉 {ticker}: Downgraded — {title}",
    "earnings": "💰 {ticker}: {title}",
    "breaking": "🔴 Breaking: {title}",
}

# High-impact categories that warrant notifications even without watchlist match
ALERT_CATEGORIES = {"upgrade", "downgrade", "earnings", "fda", "m&a"}


def check_and_notify(article: dict, conn) -> int:
    """Check if article matches any user's watchlist and send notifications.

    Args:
        article: Article dict with keys: title, tickers, category, url, source
        conn: SQLite connection

    Returns:
        Number of notifications sent
    """
    tickers = article.get("tickers", [])
    category = article.get("category", "general")
    title = article.get("title", "")

    if not tickers and category not in ALERT_CATEGORIES:
        return 0

    # Find users whose watchlist matches any of the article's tickers
    sent = 0
    for ticker in tickers:
        # Get all users watching this ticker
        rows = conn.execute(
            "SELECT DISTINCT dt.token, dt.platform, dt.user_id FROM device_tokens dt "
            "JOIN user_watchlists uw ON dt.user_id = uw.user_id "
            "WHERE uw.ticker = ?",
            (ticker.upper(),)
        ).fetchall()

        for row in rows:
            token = row["token"]
            platform = row["platform"]

            # Determine notification template
            if category in ("upgrade",):
                template = NOTIFICATION_CATEGORIES["upgrade"]
            elif category in ("downgrade",):
                template = NOTIFICATION_CATEGORIES["downgrade"]
            elif category == "earnings":
                template = NOTIFICATION_CATEGORIES["earnings"]
            else:
                template = NOTIFICATION_CATEGORIES["watchlist"]

            body = template.format(ticker=ticker, title=title[:100])

            success = _send_push(token, platform, "NewsAgent", body, {
                "url": article.get("url", ""),
                "ticker": ticker,
                "category": category,
            })
            if success:
                sent += 1

    return sent


def _send_push(token: str, platform: str, title: str, body: str, data: dict = None) -> bool:
    """Send a push notification via Firebase Cloud Messaging.

    Returns True if sent successfully, False otherwise.
    When firebase-admin is not configured, logs the notification instead.
    """
    try:
        # Try to use firebase-admin if available
        import firebase_admin
        from firebase_admin import messaging

        if not firebase_admin._apps:
            logger.info(f"[DRY RUN] Push: {title} — {body} → {token[:20]}...")
            return False

        message = messaging.Message(
            notification=messaging.Notification(title=title, body=body),
            data={k: str(v) for k, v in (data or {}).items()},
            token=token,
        )

        if platform == "ios":
            message.apns = messaging.APNSConfig(
                payload=messaging.APNSPayload(
                    aps=messaging.Aps(sound="default", badge=1)
                )
            )
        elif platform == "android":
            message.android = messaging.AndroidConfig(
                priority="high",
                notification=messaging.AndroidNotification(sound="default"),
            )

        response = messaging.send(message)
        logger.info(f"Push sent: {response}")
        return True

    except ImportError:
        # firebase-admin not installed — log instead
        logger.info(f"[NO FCM] Push would send: {title} — {body} → {token[:20]}...")
        return False
    except Exception as e:
        logger.warning(f"Push failed: {e}")
        return False


def init_firebase(credentials_path: str) -> bool:
    """Initialize Firebase Admin SDK. Call once at startup."""
    if not credentials_path:
        logger.info("Firebase not configured (no credentials path). Push notifications disabled.")
        return False
    try:
        import firebase_admin
        from firebase_admin import credentials

        if not firebase_admin._apps:
            cred = credentials.Certificate(credentials_path)
            firebase_admin.initialize_app(cred)
            logger.info("Firebase Admin SDK initialized.")
        return True
    except ImportError:
        logger.info("firebase-admin not installed. Push notifications disabled.")
        return False
    except Exception as e:
        logger.warning(f"Firebase init failed: {e}")
        return False

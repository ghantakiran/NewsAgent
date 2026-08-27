"""Tests for the TradingView alert pipeline.

Covers the alert coalescer (in-memory grouping), the TradingView webhook +
read endpoints, and the alert_groups SQLite roundtrip.
"""

import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import backend.config
import backend.routers.tradingview as tv_router
from backend.main import app
from backend.core.database import (
    get_recent_alert_groups,
    init_db,
    upsert_alert_group,
)
from backend.core.deps import get_db
from backend.services import alert_coalescer


@pytest.fixture(autouse=True)
def reset_coalescer():
    """The coalescer keeps module-level in-memory state — reset between tests."""
    alert_coalescer._groups.clear()
    yield
    alert_coalescer._groups.clear()


@pytest.fixture
def webhook_token(monkeypatch):
    """Set the webhook token on both the config module and the already-bound
    router import. The token is read at import time, so patching env vars at
    runtime is not enough."""
    token = "test-secret-token"
    monkeypatch.setattr(backend.config, "TRADINGVIEW_WEBHOOK_TOKEN", token)
    monkeypatch.setattr(tv_router, "TRADINGVIEW_WEBHOOK_TOKEN", token)
    return token


@pytest.fixture
def alert_db():
    """Isolated SQLite connection with the schema initialized."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    conn = sqlite3.connect(tmp.name, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    init_db(conn)
    yield conn
    conn.close()
    Path(tmp.name).unlink(missing_ok=True)


@pytest.fixture
def alert_client(alert_db):
    """TestClient with get_db overridden to use the isolated alert_db."""
    app.dependency_overrides[get_db] = lambda: alert_db
    yield TestClient(app)
    app.dependency_overrides.pop(get_db, None)


def _alert(ticker="AAPL", category="earnings", **kw):
    base = {
        "ticker": ticker,
        "category": category,
        "signal": "buy",
        "timeframe": "5m",
        "price": 100.0,
        "message": "test alert",
    }
    base.update(kw)
    return base


class TestCoalescer:
    def test_first_alert_is_new(self):
        event, group = alert_coalescer.coalesce(_alert())
        assert event == "new"
        assert group["count"] == 1
        assert group["ticker"] == "AAPL"
        assert group["category"] == "earnings"
        assert group["history"] == [_alert()]
        assert group["latest"] == _alert()

    def test_same_key_within_window_is_update(self):
        e1, g1 = alert_coalescer.coalesce(_alert(message="first"))
        e2, g2 = alert_coalescer.coalesce(_alert(message="second"))
        assert e1 == "new"
        assert e2 == "update"
        # Same group, count incremented.
        assert g2["group_id"] == g1["group_id"]
        assert g2["count"] == 2
        # latest reflects the most recent alert; history accumulates.
        assert g2["latest"]["message"] == "second"
        assert [a["message"] for a in g2["history"]] == ["first", "second"]

    def test_different_key_is_new(self):
        e1, g1 = alert_coalescer.coalesce(_alert(ticker="AAPL"))
        e2, g2 = alert_coalescer.coalesce(_alert(ticker="NVDA"))
        assert e1 == "new"
        assert e2 == "new"
        assert g1["group_id"] != g2["group_id"]
        assert g2["count"] == 1

    def test_group_id_stable_for_same_key_fields(self):
        # group key is "category,ticker" — other fields must not affect the id.
        _, g1 = alert_coalescer.coalesce(
            _alert(signal="buy", timeframe="5m", price=1.0, message="a")
        )
        _, g2 = alert_coalescer.coalesce(
            _alert(signal="sell", timeframe="1h", price=99.0, message="b")
        )
        assert g1["group_id"] == g2["group_id"]

    def test_group_id_changes_with_key_fields(self):
        _, g1 = alert_coalescer.coalesce(_alert(ticker="AAPL", category="earnings"))
        _, g2 = alert_coalescer.coalesce(_alert(ticker="AAPL", category="fda"))
        assert g1["group_id"] != g2["group_id"]

    def test_expired_window_opens_new_group(self, monkeypatch):
        e1, g1 = alert_coalescer.coalesce(_alert())
        assert e1 == "new"
        # Backdate last_seen beyond the coalesce window.
        gid = g1["group_id"]
        stale = (
            datetime.now(timezone.utc)
            - timedelta(seconds=backend.config.COALESCE_WINDOW_SECONDS + 10)
        ).isoformat()
        alert_coalescer._groups[gid]["last_seen"] = stale
        e2, g2 = alert_coalescer.coalesce(_alert())
        assert e2 == "new"
        assert g2["group_id"] == gid  # same key -> same id
        assert g2["count"] == 1  # but a fresh group, count reset


class TestNormalize:
    def test_symbol_alias_and_uppercase(self):
        n = tv_router._normalize({"symbol": "aapl"})
        assert n["ticker"] == "AAPL"

    def test_action_alias_maps_to_signal(self):
        n = tv_router._normalize({"action": "BUY"})
        assert n["signal"] == "buy"

    def test_tf_alias_maps_to_timeframe(self):
        n = tv_router._normalize({"tf": "15m"})
        assert n["timeframe"] == "15m"

    def test_msg_alias_maps_to_message(self):
        n = tv_router._normalize({"msg": "hello"})
        assert n["message"] == "hello"

    def test_explicit_fields_win_over_aliases(self):
        n = tv_router._normalize({"ticker": "tsla", "symbol": "aapl"})
        assert n["ticker"] == "TSLA"

    def test_price_coercion(self):
        assert tv_router._normalize({"price": "12.5"})["price"] == 12.5
        assert tv_router._normalize({"price": ""})["price"] is None
        assert tv_router._normalize({"price": "notanumber"})["price"] is None

    def test_extra_captures_only_unknown_fields(self):
        # Canonical fields AND their aliases are consumed; only truly unknown
        # keys land in `extra`.
        n = tv_router._normalize({"ticker": "AAPL", "symbol": "x", "tf": "5m", "foo": "bar"})
        assert n["extra"] == {"foo": "bar"}


class TestWebhook:
    def test_valid_token_json_body(self, alert_client, webhook_token):
        resp = alert_client.post(
            "/api/v1/webhook/tradingview",
            params={"token": webhook_token},
            json=_alert(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["event"] == "new"
        assert "group_id" in data
        assert data["count"] == 1

    def test_bad_token_401(self, alert_client, webhook_token):
        resp = alert_client.post(
            "/api/v1/webhook/tradingview",
            params={"token": "wrong"},
            json=_alert(),
        )
        assert resp.status_code == 401

    def test_unset_token_503(self, alert_client, monkeypatch):
        monkeypatch.setattr(backend.config, "TRADINGVIEW_WEBHOOK_TOKEN", "")
        monkeypatch.setattr(tv_router, "TRADINGVIEW_WEBHOOK_TOKEN", "")
        resp = alert_client.post(
            "/api/v1/webhook/tradingview",
            params={"token": "anything"},
            json=_alert(),
        )
        assert resp.status_code == 503

    def test_token_in_json_body(self, alert_client, webhook_token):
        body = _alert()
        body["token"] = webhook_token
        resp = alert_client.post("/api/v1/webhook/tradingview", json=body)
        assert resp.status_code == 200
        assert resp.json()["event"] == "new"

    def test_plain_text_body(self, alert_client, webhook_token):
        resp = alert_client.post(
            "/api/v1/webhook/tradingview",
            params={"token": webhook_token},
            content="AAPL broke resistance",
            headers={"Content-Type": "text/plain"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["event"] == "new"

    def test_coalesces_into_update(self, alert_client, webhook_token):
        r1 = alert_client.post(
            "/api/v1/webhook/tradingview",
            params={"token": webhook_token},
            json=_alert(),
        )
        r2 = alert_client.post(
            "/api/v1/webhook/tradingview",
            params={"token": webhook_token},
            json=_alert(message="again"),
        )
        assert r1.json()["event"] == "new"
        assert r2.json()["event"] == "update"
        assert r2.json()["group_id"] == r1.json()["group_id"]
        assert r2.json()["count"] == 2

    def test_get_alerts_returns_persisted_groups(self, alert_client, webhook_token):
        alert_client.post(
            "/api/v1/webhook/tradingview",
            params={"token": webhook_token},
            json=_alert(ticker="AAPL"),
        )
        alert_client.post(
            "/api/v1/webhook/tradingview",
            params={"token": webhook_token},
            json=_alert(ticker="NVDA"),
        )
        resp = alert_client.get("/api/v1/alerts")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        tickers = {g["ticker"] for g in data["groups"]}
        assert tickers == {"AAPL", "NVDA"}


class TestDatabaseRoundtrip:
    def test_upsert_and_get_roundtrip(self, alert_db):
        now = datetime.now(timezone.utc).isoformat()
        group = {
            "group_id": "abc123def456",
            "category": "earnings",
            "ticker": "AAPL",
            "timeframe": "5m",
            "signal": "buy",
            "count": 3,
            "first_seen": now,
            "last_seen": now,
            "latest": {"message": "latest one"},
            "history": [{"message": "a"}, {"message": "b"}],
        }
        upsert_alert_group(alert_db, group)
        rows = get_recent_alert_groups(alert_db)
        assert len(rows) == 1
        r = rows[0]
        assert r["group_id"] == "abc123def456"
        assert r["category"] == "earnings"
        assert r["ticker"] == "AAPL"
        assert r["count"] == 3
        assert r["latest"] == {"message": "latest one"}
        assert r["history"] == [{"message": "a"}, {"message": "b"}]

    def test_upsert_replaces_existing(self, alert_db):
        now = datetime.now(timezone.utc).isoformat()
        group = {
            "group_id": "samegid",
            "category": "earnings",
            "ticker": "AAPL",
            "timeframe": "",
            "signal": "",
            "count": 1,
            "first_seen": now,
            "last_seen": now,
            "latest": {},
            "history": [],
        }
        upsert_alert_group(alert_db, group)
        group["count"] = 5
        upsert_alert_group(alert_db, group)
        rows = get_recent_alert_groups(alert_db)
        assert len(rows) == 1
        assert rows[0]["count"] == 5

    def test_get_recent_excludes_old(self, alert_db):
        old = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
        upsert_alert_group(alert_db, {
            "group_id": "oldgid",
            "category": "general",
            "ticker": "OLD",
            "timeframe": "",
            "signal": "",
            "count": 1,
            "first_seen": old,
            "last_seen": old,
            "latest": {},
            "history": [],
        })
        rows = get_recent_alert_groups(alert_db, hours=24)
        assert rows == []

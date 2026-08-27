"""Tests for FastAPI API endpoints."""


def test_root(client):
    resp = client.get("/")
    assert resp.status_code == 200
    data = resp.json()
    assert data["app"] == "NewsAgent API"
    assert "version" in data


def test_stats(client):
    resp = client.get("/api/v1/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert "article_count" in data
    assert "active_sources" in data
    assert "refresh_interval" in data


def test_articles(client):
    resp = client.get("/api/v1/articles", params={"limit": 5})
    assert resp.status_code == 200
    data = resp.json()
    assert "articles" in data
    assert "total" in data
    assert "deduped_count" in data
    assert isinstance(data["articles"], list)


def test_articles_with_category(client):
    resp = client.get("/api/v1/articles", params={"category": "earnings", "limit": 5})
    assert resp.status_code == 200
    data = resp.json()
    for article in data["articles"]:
        assert article["category"] == "earnings"


def test_articles_breaking(client):
    resp = client.get("/api/v1/articles/breaking")
    assert resp.status_code == 200
    data = resp.json()
    assert "articles" in data
    assert "count" in data


def test_articles_tickers(client):
    resp = client.get("/api/v1/articles/tickers")
    assert resp.status_code == 200
    data = resp.json()
    assert "tickers" in data
    assert isinstance(data["tickers"], list)


def test_upgrades_downgrades(client):
    resp = client.get("/api/v1/upgrades-downgrades")
    assert resp.status_code == 200
    data = resp.json()
    assert "upgrades" in data
    assert "downgrades" in data
    assert "mixed" in data
    assert "total" in data
    assert "grade_counts" in data


def test_earnings(client):
    resp = client.get("/api/v1/earnings")
    assert resp.status_code == 200
    data = resp.json()
    assert "results" in data
    assert "total" in data


def test_catalysts(client):
    # /catalysts now returns scored catalyst events, not raw articles.
    resp = client.get("/api/v1/catalysts")
    assert resp.status_code == 200
    data = resp.json()
    assert "catalysts" in data and "total" in data
    for c in data["catalysts"]:
        assert {"id", "ticker", "type", "label", "score", "direction"} <= set(c)
        assert 0 <= c["score"] <= 100


def test_catalysts_with_type(client):
    # Legacy category names stay valid so existing mobile clients keep working.
    resp = client.get("/api/v1/catalysts", params={"type": "fda"})
    assert resp.status_code == 200
    assert "catalysts" in resp.json()


def test_catalysts_filters(client):
    for params in (
        {"group": "clinical"},
        {"direction": "bullish"},
        {"min_score": 50},
        {"confirmed_only": True},
        {"order": "move"},
        {"ticker": "NVDA"},
    ):
        resp = client.get("/api/v1/catalysts", params=params)
        assert resp.status_code == 200, params


def test_catalysts_min_score_is_respected(client):
    resp = client.get("/api/v1/catalysts", params={"min_score": 60, "limit": 50})
    assert resp.status_code == 200
    assert all(c["score"] >= 60 for c in resp.json()["catalysts"])


def test_catalyst_stats(client):
    resp = client.get("/api/v1/catalysts/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert {"total", "high_impact", "confirmed", "tickers", "by_group"} <= set(data)


def test_catalyst_detail_404(client):
    assert client.get("/api/v1/catalysts/does-not-exist").status_code == 404


def test_feeds(client):
    resp = client.get("/api/v1/feeds")
    assert resp.status_code == 200
    data = resp.json()
    assert "feeds" in data
    assert len(data["feeds"]) > 0  # Should have default feeds


def test_auth_register(client):
    import uuid
    email = f"test_{uuid.uuid4().hex[:8]}@example.com"
    resp = client.post("/api/v1/auth/register", json={
        "email": email,
        "password": "testpass123",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"


def test_auth_register_duplicate(client):
    import uuid
    email = f"test_{uuid.uuid4().hex[:8]}@example.com"
    # Register first time
    client.post("/api/v1/auth/register", json={"email": email, "password": "pass"})
    # Register again - should fail
    resp = client.post("/api/v1/auth/register", json={"email": email, "password": "pass"})
    assert resp.status_code == 409


def test_auth_login(client):
    import uuid
    email = f"test_{uuid.uuid4().hex[:8]}@example.com"
    # Register
    client.post("/api/v1/auth/register", json={"email": email, "password": "testpass"})
    # Login
    resp = client.post("/api/v1/auth/login", json={"email": email, "password": "testpass"})
    assert resp.status_code == 200
    assert "access_token" in resp.json()


def test_auth_login_wrong_password(client):
    import uuid
    email = f"test_{uuid.uuid4().hex[:8]}@example.com"
    client.post("/api/v1/auth/register", json={"email": email, "password": "testpass"})
    resp = client.post("/api/v1/auth/login", json={"email": email, "password": "wrong"})
    assert resp.status_code == 401


def test_auth_refresh(client):
    import uuid
    email = f"test_{uuid.uuid4().hex[:8]}@example.com"
    reg = client.post("/api/v1/auth/register", json={"email": email, "password": "pass"})
    refresh_token = reg.json()["refresh_token"]
    resp = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert resp.status_code == 200
    assert "access_token" in resp.json()


def test_watchlist_requires_auth(client):
    resp = client.get("/api/v1/user/watchlist")
    assert resp.status_code == 401


def test_watchlist_crud(client, auth_headers):
    # Get empty watchlist
    resp = client.get("/api/v1/user/watchlist", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["tickers"] == []

    # Set watchlist
    resp = client.put("/api/v1/user/watchlist", headers=auth_headers, json={
        "tickers": ["AAPL", "NVDA", "TSLA"]
    })
    assert resp.status_code == 200
    assert set(resp.json()["tickers"]) == {"AAPL", "NVDA", "TSLA"}

    # Get updated watchlist
    resp = client.get("/api/v1/user/watchlist", headers=auth_headers)
    assert len(resp.json()["tickers"]) == 3


def test_user_settings(client, auth_headers):
    # Get default settings
    resp = client.get("/api/v1/user/settings", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["timezone"] == "America/New_York"

    # Update settings
    resp = client.put("/api/v1/user/settings", headers=auth_headers, json={
        "timezone": "Asia/Tokyo",
    })
    assert resp.status_code == 200
    assert resp.json()["timezone"] == "Asia/Tokyo"

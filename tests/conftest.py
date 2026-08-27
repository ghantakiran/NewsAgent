"""Shared test fixtures."""

import sqlite3
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.core.database import get_connection, init_db
from backend.services.catalyst_service import init_catalyst_tables


@pytest.fixture(scope="session", autouse=True)
def _schema():
    """Create the schema the API expects before any request is made.

    TestClient is used without entering its lifespan, so the startup hook that
    normally calls init_db never runs. Locally this passed only because a
    developer database already existed on disk; on a clean checkout every
    endpoint failed with "no such table".
    """
    conn = get_connection()
    try:
        init_db(conn)
        init_catalyst_tables(conn)
    finally:
        conn.close()


@pytest.fixture
def client(_schema):
    """FastAPI test client."""
    return TestClient(app)


@pytest.fixture
def db_conn():
    """Fresh SQLite connection with initialized schema."""
    # Use a temporary database
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    conn = sqlite3.connect(tmp.name, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    init_db(conn)
    yield conn
    conn.close()
    Path(tmp.name).unlink(missing_ok=True)


@pytest.fixture
def auth_headers(client):
    """Register a test user and return auth headers."""
    resp = client.post("/api/v1/auth/register", json={
        "email": f"test_{id(client)}@example.com",
        "password": "testpass123",
    })
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}

"""FastAPI dependencies for database connections and authentication."""

import sqlite3
from typing import Generator

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .auth import decode_token
from .database import get_connection, get_user_by_id

security = HTTPBearer(auto_error=False)


def get_db() -> Generator[sqlite3.Connection, None, None]:
    """Yield a database connection, closing it after the request."""
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict | None:
    """Get current user from JWT token. Returns None for unauthenticated requests."""
    if credentials is None:
        return None
    payload = decode_token(credentials.credentials)
    if payload is None or payload.get("type") != "access":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    user = get_user_by_id(conn, int(payload["sub"]))
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user


def require_auth(user: dict | None = Depends(get_current_user)) -> dict:
    """Require authentication — raises 401 if not authenticated."""
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    return user

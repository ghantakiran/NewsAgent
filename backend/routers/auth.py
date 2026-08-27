"""Authentication endpoints — register, login, token refresh."""

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, status

from ..core.auth import create_access_token, create_refresh_token, decode_token, hash_password, verify_password
from ..core.database import create_user, get_user_by_email
from ..core.deps import get_db
from ..models.schemas import TokenRefresh, TokenResponse, UserLogin, UserRegister

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse)
def register(data: UserRegister, conn: sqlite3.Connection = Depends(get_db)):
    existing = get_user_by_email(conn, data.email)
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")
    hashed = hash_password(data.password)
    user_id = create_user(conn, data.email, hashed)
    return TokenResponse(
        access_token=create_access_token(user_id),
        refresh_token=create_refresh_token(user_id),
    )


@router.post("/login", response_model=TokenResponse)
def login(data: UserLogin, conn: sqlite3.Connection = Depends(get_db)):
    user = get_user_by_email(conn, data.email)
    if not user or not verify_password(data.password, user["hashed_password"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    return TokenResponse(
        access_token=create_access_token(user["id"]),
        refresh_token=create_refresh_token(user["id"]),
    )


@router.post("/refresh", response_model=TokenResponse)
def refresh_token(data: TokenRefresh):
    payload = decode_token(data.refresh_token)
    if payload is None or payload.get("type") != "refresh":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")
    user_id = int(payload["sub"])
    return TokenResponse(
        access_token=create_access_token(user_id),
        refresh_token=create_refresh_token(user_id),
    )

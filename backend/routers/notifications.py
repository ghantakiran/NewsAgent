"""Notification endpoints — device token registration."""

import sqlite3
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..core.deps import get_db, require_auth

router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])


class DeviceTokenRegister(BaseModel):
    token: str
    platform: str  # "ios" or "android"


class DeviceTokenResponse(BaseModel):
    status: str
    token: str


@router.post("/register-device", response_model=DeviceTokenResponse)
def register_device(
    data: DeviceTokenRegister,
    user: dict = Depends(require_auth),
    conn: sqlite3.Connection = Depends(get_db),
):
    """Register a device token for push notifications."""
    # Upsert: update user_id if token already exists, or insert new
    existing = conn.execute(
        "SELECT id FROM device_tokens WHERE token = ?", (data.token,)
    ).fetchone()

    if existing:
        conn.execute(
            "UPDATE device_tokens SET user_id = ?, platform = ? WHERE token = ?",
            (user["id"], data.platform, data.token),
        )
    else:
        conn.execute(
            "INSERT INTO device_tokens (user_id, platform, token) VALUES (?, ?, ?)",
            (user["id"], data.platform, data.token),
        )
    conn.commit()

    return DeviceTokenResponse(status="ok", token=data.token)


@router.delete("/unregister-device")
def unregister_device(
    data: DeviceTokenRegister,
    user: dict = Depends(require_auth),
    conn: sqlite3.Connection = Depends(get_db),
):
    """Remove a device token."""
    conn.execute(
        "DELETE FROM device_tokens WHERE token = ? AND user_id = ?",
        (data.token, user["id"]),
    )
    conn.commit()
    return {"status": "ok"}

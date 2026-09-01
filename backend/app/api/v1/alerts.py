"""
ARTH Phase 4 -- Price Alerts and Notifications

Alert types: price_above and price_below ONLY.
trigger_state (armed/triggered) prevents spam while condition remains true.
Resets to armed when condition reverses.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, field_validator

from app.core.auth import UserContext, require_active_user
from app.core.logging import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/user/alerts", tags=["alerts"])
notifications_router = APIRouter(prefix="/user/notifications", tags=["notifications"])


class CreateAlertRequest(BaseModel):
    symbol: str
    alert_type: str
    threshold: float

    @field_validator("symbol")
    @classmethod
    def sym_upper(cls, v: str) -> str:
        return v.strip().upper()

    @field_validator("alert_type")
    @classmethod
    def valid_type(cls, v: str) -> str:
        if v not in ("price_above", "price_below"):
            raise ValueError("alert_type must be price_above or price_below")
        return v

    @field_validator("threshold")
    @classmethod
    def positive_threshold(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("threshold must be positive")
        return v


class ToggleAlertRequest(BaseModel):
    is_active: bool


@router.get("")
async def list_alerts(request: Request, user: UserContext = Depends(require_active_user)) -> list:
    db = request.state.db
    rows = await db.fetch(
        "SELECT id, symbol, alert_type, threshold, is_active, trigger_state, last_evaluated_value, last_triggered_at, created_at FROM alerts WHERE user_id = $1 ORDER BY created_at DESC",
        user.user_id,
    )
    return [dict(row) for row in rows]


@router.post("")
async def create_alert(body: CreateAlertRequest, request: Request, user: UserContext = Depends(require_active_user)) -> dict:
    db = request.state.db
    count = await db.fetchval("SELECT COUNT(*) FROM alerts WHERE user_id = $1 AND is_active = true", user.user_id)
    if count >= 50:
        raise HTTPException(status_code=429, detail="Max 50 active alerts reached.")
    row = await db.fetchrow(
        "INSERT INTO alerts (user_id, symbol, alert_type, threshold) VALUES ($1, $2, $3, $4) RETURNING id, symbol, alert_type, threshold, is_active, trigger_state, created_at",
        user.user_id, body.symbol, body.alert_type, body.threshold,
    )
    return dict(row)


@router.delete("/{alert_id}")
async def delete_alert(alert_id: UUID, request: Request, user: UserContext = Depends(require_active_user)) -> dict:
    db = request.state.db
    result = await db.execute("DELETE FROM alerts WHERE id = $1 AND user_id = $2", alert_id, user.user_id)
    if result == "DELETE 0":
        raise HTTPException(status_code=404, detail="Alert not found or not yours")
    return {"success": True}


@router.patch("/{alert_id}/toggle")
async def toggle_alert(alert_id: UUID, body: ToggleAlertRequest, request: Request, user: UserContext = Depends(require_active_user)) -> dict:
    db = request.state.db
    result = await db.execute(
        "UPDATE alerts SET is_active = $1, trigger_state = $2 WHERE id = $3 AND user_id = $4",
        body.is_active, "armed" if body.is_active else "triggered", alert_id, user.user_id,
    )
    if result == "UPDATE 0":
        raise HTTPException(status_code=404, detail="Alert not found or not yours")
    return {"success": True, "is_active": body.is_active}


@notifications_router.get("")
async def list_notifications(request: Request, limit: int = 50, user: UserContext = Depends(require_active_user)) -> list:
    db = request.state.db
    rows = await db.fetch(
        "SELECT id, alert_id, title, body, is_read, created_at FROM notifications WHERE user_id = $1 ORDER BY is_read ASC, created_at DESC LIMIT $2",
        user.user_id, limit,
    )
    return [dict(row) for row in rows]


@notifications_router.get("/unread-count")
async def unread_count(request: Request, user: UserContext = Depends(require_active_user)) -> dict:
    db = request.state.db
    count = await db.fetchval("SELECT COUNT(*) FROM notifications WHERE user_id = $1 AND is_read = false", user.user_id)
    return {"unread": count}


@notifications_router.post("/{notification_id}/read")
async def mark_read(notification_id: UUID, request: Request, user: UserContext = Depends(require_active_user)) -> dict:
    db = request.state.db
    await db.execute("UPDATE notifications SET is_read = true WHERE id = $1 AND user_id = $2", notification_id, user.user_id)
    return {"success": True}


@notifications_router.post("/read-all")
async def mark_all_read(request: Request, user: UserContext = Depends(require_active_user)) -> dict:
    db = request.state.db
    await db.execute("UPDATE notifications SET is_read = true WHERE user_id = $1 AND is_read = false", user.user_id)
    return {"success": True}

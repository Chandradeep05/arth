"""
ARTH Phase 4 -- Admin Control Plane

All routes require require_admin (checks profiles.role = "admin" from DB).
Admin role is never from JWT claims -- always resolved from Postgres.
"""
from __future__ import annotations

import secrets
import string
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request

from app.core.auth import UserContext, require_admin
from app.core.logging import get_logger
from app.models.schemas.user import (
    CreateInviteCodeRequest,
    UpdateUserRoleRequest,
    UpdateUserStatusRequest,
)

logger = get_logger(__name__)
router = APIRouter(prefix="/admin", tags=["admin"])

INVITE_CHARS = string.ascii_uppercase + string.digits


def _gen_code(length: int = 10) -> str:
    return "".join(secrets.choice(INVITE_CHARS) for _ in range(length))


@router.get("/users")
async def list_users(request: Request, admin: UserContext = Depends(require_admin)) -> list:
    db = request.state.db
    rows = await db.fetch(
        "SELECT id, email, display_name, access_status, role, created_at FROM profiles ORDER BY created_at DESC"
    )
    return [dict(row) for row in rows]


@router.put("/users/{user_id}/status")
async def update_user_status(
    user_id: UUID,
    body: UpdateUserStatusRequest,
    request: Request,
    admin: UserContext = Depends(require_admin),
) -> dict:
    db = request.state.db
    result = await db.execute(
        "UPDATE profiles SET access_status = $1, updated_at = $2 WHERE id = $3",
        body.access_status, datetime.now(timezone.utc), user_id,
    )
    if result == "UPDATE 0":
        raise HTTPException(status_code=404, detail="User not found")
    logger.info("admin_status_updated", admin=str(admin.user_id), target=str(user_id), status=body.access_status)
    return {"success": True, "user_id": str(user_id), "access_status": body.access_status}


@router.put("/users/{user_id}/role")
async def update_user_role(
    user_id: UUID,
    body: UpdateUserRoleRequest,
    request: Request,
    admin: UserContext = Depends(require_admin),
) -> dict:
    db = request.state.db
    if body.role == "user":
        admin_count = await db.fetchval("SELECT COUNT(*) FROM profiles WHERE role = $1", "admin")
        target_role = await db.fetchval("SELECT role FROM profiles WHERE id = $1", user_id)
        if target_role == "admin" and admin_count <= 1:
            raise HTTPException(status_code=409, detail="Cannot demote the last admin.")
    result = await db.execute(
        "UPDATE profiles SET role = $1, updated_at = $2 WHERE id = $3",
        body.role, datetime.now(timezone.utc), user_id,
    )
    if result == "UPDATE 0":
        raise HTTPException(status_code=404, detail="User not found")
    return {"success": True, "user_id": str(user_id), "role": body.role}


@router.post("/invite-codes")
async def create_invite_code(
    body: CreateInviteCodeRequest,
    request: Request,
    admin: UserContext = Depends(require_admin),
) -> dict:
    db = request.state.db
    code = _gen_code()
    row = await db.fetchrow(
        "INSERT INTO invite_codes (code, created_by, expires_at) VALUES ($1, $2, $3) RETURNING id, code, used_by, used_at, expires_at",
        code, admin.user_id, body.expires_at,
    )
    logger.info("invite_created", admin=str(admin.user_id), code=code)
    return dict(row)


@router.get("/invite-codes")
async def list_invite_codes(request: Request, admin: UserContext = Depends(require_admin)) -> list:
    db = request.state.db
    rows = await db.fetch("SELECT id, code, used_by, used_at, expires_at FROM invite_codes ORDER BY id DESC")
    return [dict(row) for row in rows]


@router.get("/usage")
async def get_usage(request: Request, admin: UserContext = Depends(require_admin)) -> dict:
    db = request.state.db
    return {
        "users": {
            "total": await db.fetchval("SELECT COUNT(*) FROM profiles"),
            "active": await db.fetchval("SELECT COUNT(*) FROM profiles WHERE access_status = $1", "active"),
            "pending": await db.fetchval("SELECT COUNT(*) FROM profiles WHERE access_status = $1", "pending"),
        },
        "conversations": {"total": await db.fetchval("SELECT COUNT(*) FROM conversations")},
        "alerts": {"active": await db.fetchval("SELECT COUNT(*) FROM alerts WHERE is_active = true")},
        "recent_jobs": [dict(r) for r in await db.fetch(
            "SELECT job_type, status, created_at FROM background_jobs ORDER BY created_at DESC LIMIT 20"
        )],
    }

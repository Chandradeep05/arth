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

from app.core.auth import UserContext, require_admin, hash_invite_code
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
    if user_id == admin.user_id:
        raise HTTPException(status_code=409, detail="Cannot change your own status.")
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
    async with db.transaction():
        # Advisory lock serializes ALL admin role changes system-wide
        await db.execute("SELECT pg_advisory_xact_lock(42)")
        
        target_role = await db.fetchval("SELECT role FROM profiles WHERE id = $1", user_id)
        if target_role == "admin" and body.role != "admin":
            admin_count = await db.fetchval("SELECT COUNT(*) FROM profiles WHERE role = 'admin'")
            if admin_count <= 1:
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
    raw_code = _gen_code()
    code_hash = hash_invite_code(raw_code)
    row = await db.fetchrow(
        "INSERT INTO invite_codes (code, created_by, expires_at) VALUES ($1, $2, $3) RETURNING id, code, used_by, used_at, expires_at",
        code_hash, admin.user_id, body.expires_at,
    )
    logger.info("invite_created", admin=str(admin.user_id), code_prefix=raw_code[:4])
    res = dict(row)
    # Return plaintext raw_code once to the admin upon creation for distribution
    res["code"] = raw_code
    return res


@router.get("/invite-codes")
async def list_invite_codes(request: Request, admin: UserContext = Depends(require_admin)) -> list:
    db = request.state.db
    rows = await db.fetch("""
        SELECT 
            ic.id, 
            ic.code, 
            ic.created_by,
            p.email as user_email,
            ic.used_by, 
            ic.used_at, 
            ic.expires_at 
        FROM invite_codes ic
        LEFT JOIN profiles p ON ic.created_by = p.id
        ORDER BY ic.id DESC
    """)
    res_rows = []
    for row in rows:
        d = dict(row)
        c = d.get("code") or ""
        is_used = d.get("used_by") is not None
        # Hashed codes (64-char) are never shown as copyable text.
        # Used codes cannot be regenerated; unused codes can.
        if len(c) == 64:
            d["code"] = None  # Not available — use regenerate endpoint for unused entries
            d["code_available"] = False
            d["is_regeneratable"] = not is_used
        else:
            # Plaintext code (legacy entries or freshly generated) — still mask after use
            d["code_available"] = not is_used
            d["is_regeneratable"] = not is_used
            if is_used:
                d["code"] = None
        res_rows.append(d)
    return res_rows


@router.post("/invite-codes/{invite_id}/regenerate")
async def regenerate_invite_code(
    invite_id: str,
    request: Request,
    admin: UserContext = Depends(require_admin),
) -> dict:
    """Regenerate a new invite code for an unused invite and show once to admin."""
    from uuid import UUID
    db = request.state.db
    try:
        inv_uuid = UUID(invite_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid invite ID")

    row = await db.fetchrow(
        "SELECT id, used_by FROM invite_codes WHERE id = $1", inv_uuid
    )
    if not row:
        raise HTTPException(status_code=404, detail="Invite code not found")
    if row["used_by"] is not None:
        raise HTTPException(status_code=400, detail="Cannot regenerate an already used invite code")

    raw_code = _gen_code()
    code_hash = hash_invite_code(raw_code)
    from datetime import timedelta
    new_expires_at = datetime.now(timezone.utc) + timedelta(days=30)
    await db.execute(
        "UPDATE invite_codes SET code = $1, expires_at = $2 WHERE id = $3",
        code_hash, new_expires_at, inv_uuid,
    )
    logger.info("invite_regenerated", admin=str(admin.user_id), invite_id=invite_id)
    return {
        "success": True,
        "id": str(inv_uuid),
        "code": raw_code,
        "message": "Invite code regenerated. Copy and share it now; it cannot be shown again."
    }


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

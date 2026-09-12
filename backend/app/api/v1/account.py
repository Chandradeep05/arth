"""
ARTH Phase 4 -- Account Deletion

DELETE /api/v1/user/account
    Two-part delete:
    1. Delete Supabase auth.users record (via Admin API)
    2. Delete profiles row (CASCADE handles all child tables)

    If step 1 fails, abort — don't leave user in half-deleted state.
"""
from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request

from app.config import get_settings
from app.core.auth import UserContext, require_active_user
from app.core.logging import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/user", tags=["account"])


@router.delete("/account")
async def delete_account(
    request: Request,
    user: UserContext = Depends(require_active_user),
) -> dict:
    """
    Permanently delete the authenticated user's account and all data.

    1. Deletes Supabase auth.users via Admin API (invalidates JWT)
    2. Deletes profiles row (CASCADE to all child tables)
    """
    db = request.state.db
    settings = get_settings()

    # Prevent the last admin from deleting themselves
    role = await db.fetchval("SELECT role FROM profiles WHERE id = $1", user.user_id)
    if role == "admin":
        admin_count = await db.fetchval("SELECT COUNT(*) FROM profiles WHERE role = $1", "admin")
        if admin_count <= 1:
            raise HTTPException(
                status_code=409,
                detail="Cannot delete the last admin account. Transfer admin role first.",
            )

    # Step 1: Delete Supabase Auth user (must succeed before touching our DB)
    if settings.supabase_url and settings.supabase_service_key:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.delete(
                    f"{settings.supabase_url}/auth/v1/admin/users/{user.user_id}",
                    headers={
                        "Authorization": f"Bearer {settings.supabase_service_key}",
                        "apikey": settings.supabase_service_key,
                    },
                )
                if resp.status_code not in (200, 204):
                    logger.error(
                        "supabase_auth_delete_failed",
                        status=resp.status_code,
                        body=resp.text[:200],
                    )
                    raise HTTPException(
                        status_code=502,
                        detail="Failed to delete authentication account. Try again later.",
                    )
        except httpx.RequestError as e:
            logger.error("supabase_auth_delete_network_error", error=str(e))
            raise HTTPException(
                status_code=502,
                detail="Cannot reach authentication service. Try again later.",
            )
    else:
        logger.warning("supabase_auth_delete_skipped", reason="Supabase not configured")

    # Step 2: Delete profile + CASCADE all child tables
    await db.execute("DELETE FROM profiles WHERE id = $1", user.user_id)

    logger.info(
        "account_deleted",
        user_id=str(user.user_id),
        email=user.email,
    )

    return {
        "success": True,
        "message": "Your account and all associated data have been permanently deleted.",
    }

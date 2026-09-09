"""
ARTH Phase 4 -- Account Deletion

DELETE /api/v1/user/account
    Deletes all user data and the profile itself.
    Cascading FKs handle watchlists, conversations, messages, alerts, etc.
    Requires active user authentication (can't delete someone else's account).

PRD Section 1.3: "Account deletion: a real (if simple) 'delete my account and data' path."
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

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
    Permanently delete the authenticated user's account and all associated data.

    Because all tables have ON DELETE CASCADE referencing profiles(id),
    deleting the profile row cascades to:
    - watchlists + watchlist_items
    - conversations + messages
    - saved_research
    - alerts + notifications
    - background_jobs
    - invite_codes (created_by / used_by set to NULL via ON DELETE SET NULL)
    """
    db = request.state.db

    # Double-check the profile exists (defense against race conditions)
    exists = await db.fetchval("SELECT id FROM profiles WHERE id = $1", user.user_id)
    if not exists:
        raise HTTPException(status_code=404, detail="Profile not found")

    # Prevent the last admin from deleting themselves
    role = await db.fetchval("SELECT role FROM profiles WHERE id = $1", user.user_id)
    if role == "admin":
        admin_count = await db.fetchval("SELECT COUNT(*) FROM profiles WHERE role = $1", "admin")
        if admin_count <= 1:
            raise HTTPException(
                status_code=409,
                detail="Cannot delete the last admin account. Transfer admin role first.",
            )

    # CASCADE handles all child tables
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

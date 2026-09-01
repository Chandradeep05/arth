"""
ARTH Phase 4 -- Invite Code Redemption

POST /api/v1/auth/invite/redeem
    Validates and atomically redeems an invite code, activating the user.
    Requires: authenticated user (any access_status).
    The atomic transaction prevents double-redemption under concurrent requests.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request

from app.core.auth import UserContext, get_current_user
from app.core.logging import get_logger
from app.models.schemas.user import RedeemInviteRequest

logger = get_logger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/invite/redeem")
async def redeem_invite_code(
    body: RedeemInviteRequest,
    request: Request,
    user: UserContext = Depends(get_current_user),
) -> dict:
    """
    Redeem an invite code to activate a pending account.

    Uses a database transaction to atomically:
    1. Validate the code exists, is unused, and is not expired
    2. Mark the code as used (used_by = user_id, used_at = now)
    3. Set profiles.access_status = 'active'

    The SELECT ... FOR UPDATE inside the transaction prevents two simultaneous
    requests from both consuming the same code.
    """
    db = request.state.db
    code = body.code
    now = datetime.now(timezone.utc)

    async with db.transaction():
        # Lock the invite code row for this transaction
        invite = await db.fetchrow(
            """
            SELECT id, used_by, expires_at
            FROM invite_codes
            WHERE code = $1
            FOR UPDATE
            """,
            code,
        )

        if not invite:
            raise HTTPException(status_code=404, detail="Invite code not found")

        if invite["used_by"] is not None:
            raise HTTPException(
                status_code=409,
                detail="Invite code has already been used",
            )

        if invite["expires_at"] and invite["expires_at"] < now:
            raise HTTPException(
                status_code=410,
                detail="Invite code has expired",
            )

        # Atomically mark code as used and activate the user
        await db.execute(
            """
            UPDATE invite_codes
            SET used_by = $1, used_at = $2
            WHERE id = $3
            """,
            user.user_id,
            now,
            invite["id"],
        )

        await db.execute(
            """
            UPDATE profiles
            SET access_status = 'active', updated_at = $1
            WHERE id = $2
            """,
            now,
            user.user_id,
        )

    logger.info(
        "invite_redeemed",
        user_id=str(user.user_id),
        email=user.email,
        invite_id=str(invite["id"]),
    )

    return {
        "success": True,
        "message": "Invite code accepted. Your account is now active.",
        "access_status": "active",
    }

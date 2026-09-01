"""
ARTH Phase 4 -- User and Auth Pydantic Schemas

Request/response models for auth, profile, invite, and admin endpoints.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, EmailStr, field_validator


# -- Profile ------------------------------------------------------------------

class ProfileResponse(BaseModel):
    """User profile returned to authenticated clients."""
    id: UUID
    email: str
    display_name: Optional[str]
    avatar_url: Optional[str]
    access_status: str
    role: str
    preferences: dict
    created_at: datetime


class UpdateProfileRequest(BaseModel):
    """Fields the user can update on their own profile."""
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None
    preferences: Optional[dict] = None


# -- Invite Codes -------------------------------------------------------------

class RedeemInviteRequest(BaseModel):
    """Body for POST /auth/invite/redeem"""
    code: str

    @field_validator("code")
    @classmethod
    def code_not_empty(cls, v: str) -> str:
        v = v.strip().upper()
        if not v:
            raise ValueError("Invite code cannot be empty")
        return v


class InviteCodeResponse(BaseModel):
    """Admin view of an invite code."""
    id: UUID
    code: str
    used_by: Optional[UUID]
    used_at: Optional[datetime]
    expires_at: Optional[datetime]
    is_used: bool


class CreateInviteCodeRequest(BaseModel):
    """Admin request to create an invite code."""
    expires_at: Optional[datetime] = None


# -- Admin --------------------------------------------------------------------

class AdminUserView(BaseModel):
    """Admin view of a user profile."""
    id: UUID
    email: str
    display_name: Optional[str]
    access_status: str
    role: str
    created_at: datetime


class UpdateUserStatusRequest(BaseModel):
    """Admin request to change user access status."""
    access_status: str

    @field_validator("access_status")
    @classmethod
    def valid_status(cls, v: str) -> str:
        allowed = {"pending", "active", "suspended"}
        if v not in allowed:
            raise ValueError(f"access_status must be one of {allowed}")
        return v


class UpdateUserRoleRequest(BaseModel):
    """Admin request to change user role. Requires at least 2 admins to prevent lockout."""
    role: str

    @field_validator("role")
    @classmethod
    def valid_role(cls, v: str) -> str:
        allowed = {"user", "admin"}
        if v not in allowed:
            raise ValueError(f"role must be one of {allowed}")
        return v

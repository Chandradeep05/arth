"""
ARTH Phase 4 -- Authentication and Authorization

FastAPI dependencies for JWT validation and user authorization.

JWT Strategy:
    Supabase issues ES256 tokens for new projects (default since Oct 2025).
    Older projects may use HS256. We detect the algorithm from the token header
    so this code works correctly for both without any configuration toggle.

    HS256: verified using supabase_jwt_secret (shared secret)
    ES256: verified using JWKS fetched from Supabase public endpoint (cached)

Access Control:
    JWT establishes identity only (user_id, email).
    access_status and role are ALWAYS resolved from Postgres on every request.
    This ensures revocation takes effect immediately, not after JWT expiry.

Profile Provisioning:
    First-time Google login auto-creates a profile (pending status).
    Uses INSERT ... ON CONFLICT DO NOTHING to be concurrent-safe.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, Request
from jwt import PyJWKClient

from app.config import Settings, get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# Module-level JWKS client cache -- PyJWKClient caches public keys across requests.
# Supabase JWKS endpoint: {supabase_url}/auth/v1/.well-known/jwks.json
_jwks_clients: dict = {}


def _get_jwks_client(supabase_url: str) -> PyJWKClient:
    """Get or create a cached JWKS client for this Supabase project."""
    if supabase_url not in _jwks_clients:
        jwks_uri = f"{supabase_url}/auth/v1/.well-known/jwks.json"
        _jwks_clients[supabase_url] = PyJWKClient(jwks_uri, cache_keys=True)
        logger.info("jwks_client_created", jwks_uri=jwks_uri)
    return _jwks_clients[supabase_url]


def _decode_supabase_jwt(token: str, settings: Settings) -> dict:
    """
    Decode and verify a Supabase JWT.

    Handles both ES256 (new default since Oct 2025) and HS256 (legacy).
    Algorithm is detected from the token header -- no config flag needed.
    Always validates: algorithm, expiration, audience='authenticated'.
    Note: Missing audience= causes silent auth failures -- always include it.
    """
    try:
        header = jwt.get_unverified_header(token)
    except jwt.exceptions.DecodeError as e:
        raise HTTPException(status_code=401, detail="Malformed token") from e

    alg = header.get("alg", "")

    try:
        if alg == "ES256":
            if not settings.supabase_url:
                raise HTTPException(
                    status_code=500,
                    detail="SUPABASE_URL not configured -- cannot verify ES256 token",
                )
            jwks_client = _get_jwks_client(settings.supabase_url)
            signing_key = jwks_client.get_signing_key_from_jwt(token)
            return jwt.decode(
                token,
                signing_key.key,
                algorithms=["ES256"],
                audience="authenticated",
                options={"require": ["exp", "sub", "aud"]},
            )
        elif alg == "HS256":
            if not settings.supabase_jwt_secret:
                raise HTTPException(
                    status_code=500,
                    detail="SUPABASE_JWT_SECRET not configured -- cannot verify HS256 token",
                )
            return jwt.decode(
                token,
                settings.supabase_jwt_secret,
                algorithms=["HS256"],
                audience="authenticated",
                options={"require": ["exp", "sub", "aud"]},
            )
        else:
            raise HTTPException(
                status_code=401,
                detail=f"Unsupported JWT algorithm: {alg}",
            )
    except jwt.exceptions.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.exceptions.InvalidAudienceError:
        raise HTTPException(status_code=401, detail="Invalid token audience")
    except jwt.exceptions.InvalidSignatureError:
        raise HTTPException(status_code=401, detail="Invalid token signature")
    except jwt.exceptions.DecodeError as e:
        raise HTTPException(status_code=401, detail=f"Token decode error: {e}")
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("jwt_decode_unexpected_error", error=str(e), alg=alg)
        raise HTTPException(status_code=401, detail="Token validation failed")


def _extract_bearer_token(request: Request) -> str:
    """Extract bearer token from Authorization header."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Authorization header missing or not Bearer type",
        )
    token = auth_header[len("Bearer "):]
    if not token:
        raise HTTPException(status_code=401, detail="Bearer token is empty")
    return token


@dataclass
class UserContext:
    """
    Validated user identity for the current request.

    user_id and email: from the verified JWT.
    access_status and role: ALWAYS loaded from Postgres, never from JWT claims.
    Changes (suspend/activate, role changes) take effect on the next request.
    """
    user_id: UUID
    email: str
    access_status: str   # pending | active | suspended
    role: str            # user | admin

    @property
    def is_active(self) -> bool:
        return self.access_status == "active"

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


async def _resolve_or_create_profile(
    user_id: UUID,
    email: str,
    display_name: Optional[str],
    db,
) -> tuple:
    """
    Load (access_status, role) from profiles table.
    Auto-creates a pending profile for first-time Google login.

    Uses INSERT ... ON CONFLICT DO NOTHING -- concurrent-safe.
    Two simultaneous first-requests cannot create duplicate profiles.
    Returns: (access_status, role)
    """
    row = await db.fetchrow(
        "SELECT access_status, role FROM profiles WHERE id = $1",
        user_id,
    )
    if row:
        return row["access_status"], row["role"]

    # First-time user -- create profile atomically
    logger.info("profile_auto_creating", user_id=str(user_id), email=email)
    await db.execute(
        """
        INSERT INTO profiles (id, display_name, access_status, role)
        VALUES ($1, $2, 'pending', 'user')
        ON CONFLICT (id) DO NOTHING
        """,
        user_id,
        display_name or email.split("@")[0],
    )
    row = await db.fetchrow(
        "SELECT access_status, role FROM profiles WHERE id = $1",
        user_id,
    )
    if not row:
        logger.error("profile_create_failed", user_id=str(user_id))
        raise HTTPException(status_code=500, detail="Could not provision user profile")

    logger.info(
        "profile_created",
        user_id=str(user_id),
        email=email,
        access_status=row["access_status"],
    )
    return row["access_status"], row["role"]


# == FastAPI Dependencies =====================================================

async def get_current_user(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> UserContext:
    """
    FastAPI dependency: validate JWT and return UserContext.
    Resolves access_status and role from Postgres on every call.
    Use on routes that need identity but not necessarily active status.
    """
    token = _extract_bearer_token(request)
    payload = _decode_supabase_jwt(token, settings)

    user_id = UUID(payload["sub"])
    email = payload.get("email", "")
    user_meta = payload.get("user_metadata", {})
    display_name = user_meta.get("full_name") if isinstance(user_meta, dict) else None

    db = request.state.db
    access_status, role = await _resolve_or_create_profile(
        user_id, email, display_name, db
    )
    return UserContext(
        user_id=user_id,
        email=email,
        access_status=access_status,
        role=role,
    )


async def require_active_user(
    user: UserContext = Depends(get_current_user),
) -> UserContext:
    """
    FastAPI dependency: require authenticated + active user.
    Use on watchlist, conversation, research, alert, notification endpoints.
    """
    if user.access_status == "suspended":
        raise HTTPException(
            status_code=403,
            detail="Your account has been suspended. Contact the admin.",
        )
    if user.access_status != "active":
        raise HTTPException(
            status_code=403,
            detail=(
                "Your account is pending activation. "
                "Enter an invite code to get access, or contact the admin."
            ),
        )
    return user


async def require_admin(
    user: UserContext = Depends(get_current_user),
) -> UserContext:
    """
    FastAPI dependency: require admin role (checked from Postgres, not JWT).
    Use on /admin/* endpoints only.
    """
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required.")
    return user


def require_internal_secret(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> None:
    """
    FastAPI dependency: validate X-Internal-Secret for job trigger endpoints.
    Used on /internal/jobs/* called by GitHub Actions cron.
    Machine-to-machine only -- never browser-facing.
    """
    secret = request.headers.get("X-Internal-Secret", "")
    if not settings.internal_job_secret:
        raise HTTPException(status_code=500, detail="INTERNAL_JOB_SECRET not configured")
    if secret != settings.internal_job_secret:
        raise HTTPException(status_code=403, detail="Invalid internal job secret")

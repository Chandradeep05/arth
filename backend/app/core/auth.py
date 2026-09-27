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
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

import hmac
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

    # First-time user -- create profile atomically (includes email for admin queries)
    logger.info("profile_auto_creating", user_id=str(user_id), email=email)
    inserted = await db.fetchrow(
        """
        INSERT INTO profiles (id, email, display_name, access_status, role, last_login)
        VALUES ($1, $2, $3, 'pending', 'user', now())
        ON CONFLICT (id) DO NOTHING
        RETURNING id
        """,
        user_id,
        email,
        display_name or email.split("@")[0],
    )
    is_new_user = inserted is not None

    # Check if this email should be auto-promoted to admin
    from app.config import get_settings as _get_settings
    _settings = _get_settings()
    if _settings.initial_admin_email and email == _settings.initial_admin_email:
        # One-time bootstrap: atomic UPDATE that only promotes if no admin exists.
        # The NOT EXISTS subquery prevents the race where two concurrent first
        # logins both see zero admins and both promote.
        result = await db.execute(
            "UPDATE profiles SET role = 'admin', access_status = 'active' "
            "WHERE id = $1 AND NOT EXISTS (SELECT 1 FROM profiles WHERE role = 'admin')",
            user_id,
        )
        if result and result != 'UPDATE 0':
            logger.info("admin_bootstrap_on_first_login", email=email)
        else:
            logger.info("admin_bootstrap_skipped", email=email, reason="admin already exists")

    row = await db.fetchrow(
        "SELECT access_status, role FROM profiles WHERE id = $1",
        user_id,
    )
    if not row:
        logger.error("profile_create_failed", user_id=str(user_id))
        raise HTTPException(status_code=500, detail="Could not provision user profile")

    # Auto-generate an invite code ONLY for genuinely new pending users so admin can share it
    if is_new_user and row["access_status"] == "pending":
        try:
            await _auto_generate_invite(user_id, email, db)
        except Exception as e:
            logger.warning("auto_invite_generation_failed", error=str(e), email=email)

    logger.info(
        "profile_created",
        user_id=str(user_id),
        email=email,
        access_status=row["access_status"],
    )
    return row["access_status"], row["role"]


async def _auto_generate_invite(user_id: UUID, email: str, db) -> None:
    """
    Auto-generate a personal invite code for a new pending user.
    The code is stored in invite_codes and can be seen by admin in the admin panel.
    Also attempts to send the code via email using Supabase's admin API.
    """
    import secrets
    import string
    from datetime import timedelta

    chars = string.ascii_uppercase + string.digits
    code = "".join(secrets.choice(chars) for _ in range(10))

    # Store the invite code linked to this pending user
    await db.execute(
        """
        INSERT INTO invite_codes (code, created_by, expires_at)
        VALUES ($1, $2, $3)
        """,
        code,
        user_id,
        datetime.now(timezone.utc) + timedelta(days=30),
    )

    logger.info(
        "auto_invite_generated",
        email=email,
        code_prefix=code[:4] + "...",
    )

    # Attempt to send invite code via email
    await _send_invite_email(email, code)


async def _send_invite_email(email: str, code: str) -> None:
    """
    Send the invite code to the user's email.
    Uses a simple SMTP approach via Supabase Edge Function or direct SMTP.
    Falls back to logging the code if no email service is configured.
    """
    try:
        from app.config import get_settings as _get_settings
        settings = _get_settings()

        # If Supabase is configured, use the Admin API to send a custom email
        if settings.supabase_url and settings.supabase_service_key:
            import httpx
            async with httpx.AsyncClient(timeout=10) as client:
                # Use Supabase's built-in email via Auth Admin API
                # This sends a "magic link" style email - we repurpose the invite flow
                resp = await client.post(
                    f"{settings.supabase_url}/auth/v1/invite",
                    headers={
                        "Authorization": f"Bearer {settings.supabase_service_key}",
                        "apikey": settings.supabase_service_key,
                        "Content-Type": "application/json",
                    },
                    json={"email": email},
                )
                # Note: Supabase invite may fail if user already exists in auth.users
                # That's OK - the admin can still see the code in the admin panel
                if resp.status_code not in (200, 201, 422):
                    logger.warning(
                        "supabase_invite_email_failed",
                        status=resp.status_code,
                        email=email,
                    )

        # Always log the code so admin can find it in logs as backup
        logger.info(
            "invite_code_for_user",
            email=email,
            invite_code=code,
            message="Share this code with the user to activate their account",
        )
    except Exception as e:
        logger.warning("invite_email_send_failed", error=str(e), email=email)


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

    try:
        user_id = UUID(payload["sub"])
    except (ValueError, KeyError):
        raise HTTPException(status_code=401, detail="Invalid user identity in token")
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
    user: UserContext = Depends(require_active_user),
) -> UserContext:
    """Require active admin. Suspended admins are rejected by require_active_user first."""
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
    if not hmac.compare_digest(secret, settings.internal_job_secret):
        raise HTTPException(status_code=403, detail="Invalid internal job secret")

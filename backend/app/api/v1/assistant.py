"""
AI Assistant API endpoints.

Provides:
- POST /assistant/chat — Send message and get response (SSE streaming)
- GET /assistant/sessions — List active sessions (user-scoped)
- GET /assistant/sessions/{session_id} — Get session details (user-scoped)
- DELETE /assistant/sessions/{session_id} — Delete a session (user-scoped)

V3.2 hardening:
- All endpoints require authentication (require_active_user)
- Sessions are tenant-isolated by user_id — no cross-user leakage
- Conversation ownership verified BEFORE LLM generation (not after)
- _persist_turn is transactional: user + assistant INSERT + message_count in one txn
- Idempotency wired into streaming path — duplicate requests return existing response
- CancelledError handler persists partial content via asyncio.shield
- Non-stream path also persists to DB
- SSE uses json.dumps for all event encoding
"""

from __future__ import annotations

import asyncio
import json
import uuid as _uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.config import Settings, get_settings
from app.core.auth import UserContext, require_active_user
from app.core.logging import get_logger
from app.core.quotas import check_user_quota
from app.engines.assistant.engine import AssistantEngine

from contextlib import asynccontextmanager

logger = get_logger(__name__)
router = APIRouter(prefix="/assistant", tags=["assistant"])

# In-flight request deduplication & reservation locks per (conversation_id, idempotency_key)
_idempotency_locks: dict[str, asyncio.Lock] = {}
_idempotency_registry_lock = asyncio.Lock()


@asynccontextmanager
async def _get_db_connection(http_request: Request):
    """
    Acquire DB connection from app.state.pg_pool only for the immediate query,
    releasing it immediately to avoid holding connections across SSE streams.
    Both streaming persist paths (CancelledError and normal completion) use pool.acquire().
    Falls back to http_request.state.db if already set (e.g. in test fixtures).
    """
    db = getattr(http_request.state, "db", None)
    if db is not None:
        yield db
        return

    pool = getattr(http_request.app.state, "pg_pool", None)
    if pool is not None:
        async with pool.acquire() as conn:
            yield conn
            return

    yield None


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None
    conversation_id: str | None = None       # DB conversation UUID for persistence
    idempotency_key: str | None = None       # Prevents double-burn on retries
    stream: bool = True


@router.post("/chat")
async def chat(
    request: ChatRequest,
    http_request: Request,
    settings: Settings = Depends(get_settings),
    user: UserContext = Depends(require_active_user),
):
    """Send a message to the AI assistant.

    By default, streams the response via SSE for progressive rendering.
    Set stream=false for a complete JSON response.

    Authentication required. Backend owns persistence of user + assistant messages.
    Conversation ownership is validated BEFORE any LLM call.
    """
    engine = AssistantEngine(settings)

    # ── Idempotency Reservation Lock ──
    # Prevents concurrent requests with the same idempotency key from both calling Groq
    idem_lock = None
    if request.idempotency_key and request.conversation_id:
        lock_id = f"{request.conversation_id}:{request.idempotency_key}"
        async with _idempotency_registry_lock:
            if lock_id not in _idempotency_locks:
                _idempotency_locks[lock_id] = asyncio.Lock()
            idem_lock = _idempotency_locks[lock_id]
        await idem_lock.acquire()

    try:
        # ── Ownership check BEFORE LLM generation ──
        if request.conversation_id:
            async with _get_db_connection(http_request) as db:
                if db:
                    owned = await db.fetchval(
                        "SELECT id FROM conversations WHERE id = $1 AND user_id = $2",
                        request.conversation_id, user.user_id,
                    )
                    if not owned:
                        raise HTTPException(status_code=403, detail="Conversation not found or not yours.")

                    # ── Idempotency check with lock held ──
                    if request.idempotency_key:
                        existing = await db.fetchrow(
                            "SELECT m.content FROM messages m "
                            "WHERE m.conversation_id = $1 AND m.role = 'assistant' "
                            "AND m.idempotency_key = $2",
                            request.conversation_id, request.idempotency_key,
                        )
                        if existing:
                            # Release reservation lock before returning duplicate
                            if idem_lock and idem_lock.locked():
                                idem_lock.release()
                            if request.stream:
                                async def replay_stream():
                                    yield f"data: {json.dumps({'type': 'token', 'content': existing['content']})}\n\n"
                                    yield f"data: {json.dumps({'type': 'done', 'entities': [], 'duplicate': True})}\n\n"
                                return StreamingResponse(replay_stream(), media_type="text/event-stream")
                            else:
                                return {"success": True, "data": {"response": existing["content"], "duplicate": True}}

        # ── Quota check BEFORE LLM generation ──
        # After idempotency (duplicates don't consume quota), before expensive work
        redis_instance = getattr(http_request.app.state, "redis", None)
        await check_user_quota(user.user_id, "chat", redis_instance)

        if request.stream:
            # Pass user_id to session management for tenant isolation
            session = engine.get_or_create_session(request.session_id, user_id=str(user.user_id))

            async def event_stream():
                try:
                    yield f"data: {json.dumps({'type': 'session', 'session_id': session.session_id})}\n\n"

                    # Extract symbols and send tool usage events
                    symbols = engine._extract_symbols(request.message)
                    if symbols:
                        yield f"data: {json.dumps({'type': 'tools', 'symbols': list(symbols)})}\n\n"

                    accumulated = ""
                    persist_needed = True
                    try:
                        async for token in engine.stream_chat(request.message, session.session_id):
                            accumulated += token
                            yield f"data: {json.dumps({'type': 'token', 'content': token})}\n\n"

                        yield f"data: {json.dumps({'type': 'done', 'entities': list(session.entities)})}\n\n"

                    except asyncio.CancelledError:
                        # Client disconnected — persist partial content
                        if accumulated and request.conversation_id:
                            try:
                                async with _get_db_connection(http_request) as persist_conn:
                                    if persist_conn:
                                        await asyncio.shield(
                                            _persist_turn(
                                                persist_conn, request.conversation_id, user.user_id,
                                                request.message, accumulated,
                                                idempotency_key=request.idempotency_key,
                                            )
                                        )
                            except Exception as e:
                                logger.warning("persist_on_disconnect_failed", error=str(e))
                        raise

                    # Normal completion: persist full response
                    if persist_needed and accumulated and request.conversation_id:
                        try:
                            async with _get_db_connection(http_request) as persist_conn:
                                if persist_conn:
                                    await _persist_turn(
                                        persist_conn, request.conversation_id, user.user_id,
                                        request.message, accumulated,
                                        idempotency_key=request.idempotency_key,
                                    )
                        except Exception as e:
                            logger.warning("persist_on_complete_failed", error=str(e))
                finally:
                    if idem_lock and idem_lock.locked():
                        idem_lock.release()

            return StreamingResponse(
                event_stream(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                },
            )
        else:
            # Non-stream path
            try:
                result = await engine.chat(request.message, request.session_id, user_id=str(user.user_id))

                if result.get("error"):
                    return {"success": False, "message": result.get("message")}

                # Persist non-stream response to DB
                response_text = result.get("response", "")
                if response_text and request.conversation_id:
                    try:
                        async with _get_db_connection(http_request) as persist_conn:
                            if persist_conn:
                                await _persist_turn(
                                    persist_conn, request.conversation_id, user.user_id,
                                    request.message, response_text,
                                    idempotency_key=request.idempotency_key,
                                )
                    except Exception as e:
                        logger.warning("persist_non_stream_failed", error=str(e))

                return {"success": True, "data": result}
            finally:
                if idem_lock and idem_lock.locked():
                    idem_lock.release()
    except Exception:
        if idem_lock and idem_lock.locked():
            idem_lock.release()
        raise


@router.get("/sessions")
async def list_sessions(
    settings: Settings = Depends(get_settings),
    user: UserContext = Depends(require_active_user),
):
    """List active assistant sessions for the current user only."""
    engine = AssistantEngine(settings)
    return {
        "success": True,
        "data": engine.list_sessions(user_id=str(user.user_id)),
    }


@router.get("/sessions/{session_id}")
async def get_session(
    session_id: str,
    settings: Settings = Depends(get_settings),
    user: UserContext = Depends(require_active_user),
):
    """Get details of a specific session. User-scoped — cannot see other users' sessions."""
    engine = AssistantEngine(settings)
    session = engine.get_session(session_id, user_id=str(user.user_id))

    if session is None:
        return {"success": False, "message": "Session not found"}

    return {"success": True, "data": session.to_dict()}


@router.delete("/sessions/{session_id}")
async def delete_session(
    session_id: str,
    settings: Settings = Depends(get_settings),
    user: UserContext = Depends(require_active_user),
):
    """Delete an assistant session. User-scoped — cannot delete other users' sessions."""
    engine = AssistantEngine(settings)
    deleted = engine.delete_session(session_id, user_id=str(user.user_id))

    return {
        "success": deleted,
        "message": "Session deleted" if deleted else "Session not found",
    }


async def _persist_turn(
    db,
    conversation_id: str,
    user_id,
    user_message: str,
    assistant_response: str,
    idempotency_key: str | None = None,
) -> None:
    """Persist a user + assistant message pair to the database.

    TRANSACTIONAL: all-or-nothing. Updates message_count and updated_at.
    Idempotency: if idempotency_key is provided, the assistant message is
    stored with it for dedup on retries.
    """
    from datetime import datetime, timezone, timedelta

    now = datetime.now(timezone.utc)
    assistant_ts = now + timedelta(microseconds=1)  # Ensure ordering

    async with db.transaction():
        # Insert user message
        await db.execute(
            "INSERT INTO messages (conversation_id, role, content, created_at) VALUES ($1, $2, $3, $4)",
            conversation_id, "user", user_message, now,
        )

        # Insert assistant message (with idempotency_key if provided)
        if idempotency_key:
            await db.execute(
                "INSERT INTO messages (conversation_id, role, content, created_at, idempotency_key) "
                "VALUES ($1, $2, $3, $4, $5) "
                "ON CONFLICT (conversation_id, idempotency_key) "
                "WHERE idempotency_key IS NOT NULL DO NOTHING",
                conversation_id, "assistant", assistant_response, assistant_ts, idempotency_key,
            )
        else:
            await db.execute(
                "INSERT INTO messages (conversation_id, role, content, created_at) VALUES ($1, $2, $3, $4)",
                conversation_id, "assistant", assistant_response, assistant_ts,
            )

        # Update conversation metadata
        await db.execute(
            "UPDATE conversations SET message_count = message_count + 2, updated_at = $1 WHERE id = $2",
            assistant_ts, conversation_id,
        )

    logger.info("turn_persisted", conversation_id=conversation_id, has_idempotency=idempotency_key is not None)

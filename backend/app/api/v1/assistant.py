"""
AI Assistant API endpoints.

Provides:
- POST /assistant/chat — Send message and get response (SSE streaming)
- GET /assistant/sessions — List active sessions
- GET /assistant/sessions/{session_id} — Get session details
- DELETE /assistant/sessions/{session_id} — Delete a session

Phase 5 hardening:
- All endpoints require authentication (require_active_user)
- SSE uses json.dumps for all event encoding (no manual escaping)
- Disconnect handling: CancelledError + asyncio.shield for partial persist
"""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.config import Settings, get_settings
from app.core.auth import UserContext, require_active_user
from app.core.logging import get_logger
from app.engines.assistant.engine import AssistantEngine

logger = get_logger(__name__)
router = APIRouter(prefix="/assistant", tags=["assistant"])


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
    """
    engine = AssistantEngine(settings)

    if request.stream:
        session = engine.get_or_create_session(request.session_id)

        async def event_stream():
            yield f"data: {json.dumps({'type': 'session', 'session_id': session.session_id})}\n\n"

            # Extract symbols and send tool usage events
            symbols = engine._extract_symbols(request.message)
            if symbols:
                yield f"data: {json.dumps({'type': 'tools', 'symbols': list(symbols)})}\n\n"

            accumulated = ""
            try:
                async for token in engine.stream_chat(request.message, session.session_id):
                    accumulated += token
                    yield f"data: {json.dumps({'type': 'token', 'content': token})}\n\n"
            except asyncio.CancelledError:
                # Client disconnected mid-stream — persist what we have
                if accumulated and request.conversation_id:
                    try:
                        await asyncio.shield(
                            _persist_turn(
                                http_request, request.conversation_id,
                                user.user_id, request.message, accumulated
                            )
                        )
                    except Exception as e:
                        logger.warning("persist_on_disconnect_failed", error=str(e))
                raise  # Re-raise — don't swallow CancelledError

            yield f"data: {json.dumps({'type': 'done', 'entities': list(session.entities)})}\n\n"

            # Normal completion: persist full response
            if accumulated and request.conversation_id:
                try:
                    await _persist_turn(
                        http_request, request.conversation_id,
                        user.user_id, request.message, accumulated
                    )
                except Exception as e:
                    logger.warning("persist_on_complete_failed", error=str(e))

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
        result = await engine.chat(request.message, request.session_id)

        if result.get("error"):
            return {"success": False, "message": result.get("message")}

        return {"success": True, "data": result}


@router.get("/sessions")
async def list_sessions(
    settings: Settings = Depends(get_settings),
    user: UserContext = Depends(require_active_user),
):
    """List all active assistant sessions."""
    engine = AssistantEngine(settings)
    return {
        "success": True,
        "data": engine.list_sessions(),
    }


@router.get("/sessions/{session_id}")
async def get_session(
    session_id: str,
    settings: Settings = Depends(get_settings),
    user: UserContext = Depends(require_active_user),
):
    """Get details of a specific session."""
    engine = AssistantEngine(settings)
    session = engine.get_session(session_id)

    if session is None:
        return {"success": False, "message": "Session not found"}

    return {"success": True, "data": session.to_dict()}


@router.delete("/sessions/{session_id}")
async def delete_session(
    session_id: str,
    settings: Settings = Depends(get_settings),
    user: UserContext = Depends(require_active_user),
):
    """Delete an assistant session."""
    engine = AssistantEngine(settings)
    deleted = engine.delete_session(session_id)

    return {
        "success": deleted,
        "message": "Session deleted" if deleted else "Session not found",
    }


async def _persist_turn(
    http_request: Request,
    conversation_id: str,
    user_id,
    user_message: str,
    assistant_response: str,
) -> None:
    """Persist a user + assistant message pair to the database.

    Verifies conversation ownership before persisting — never trusts
    client-provided conversation_id alone.
    """
    from datetime import datetime, timezone, timedelta

    db = getattr(http_request.state, "db", None)
    if not db:
        logger.warning("persist_turn_no_db")
        return

    # Ownership check — never trust client-provided conversation_id alone
    owned = await db.fetchval(
        "SELECT id FROM conversations WHERE id = $1 AND user_id = $2",
        conversation_id, user_id
    )
    if not owned:
        logger.warning("persist_denied", conversation_id=conversation_id, user_id=str(user_id))
        return

    now = datetime.now(timezone.utc)
    assistant_ts = now + timedelta(microseconds=1)  # Ensure ordering

    await db.execute(
        "INSERT INTO messages (conversation_id, role, content, created_at) VALUES ($1, $2, $3, $4)",
        conversation_id, "user", user_message, now
    )
    await db.execute(
        "INSERT INTO messages (conversation_id, role, content, created_at) VALUES ($1, $2, $3, $4)",
        conversation_id, "assistant", assistant_response, assistant_ts
    )
    logger.info("turn_persisted", conversation_id=conversation_id)

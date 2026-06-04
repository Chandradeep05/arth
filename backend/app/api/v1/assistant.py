"""
AI Assistant API endpoints.

Provides:
- POST /assistant/chat — Send message and get response (SSE streaming)
- GET /assistant/sessions — List active sessions
- GET /assistant/sessions/{session_id} — Get session details
- DELETE /assistant/sessions/{session_id} — Delete a session
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.config import Settings, get_settings
from app.core.logging import get_logger
from app.engines.assistant.engine import AssistantEngine

logger = get_logger(__name__)
router = APIRouter(prefix="/assistant", tags=["assistant"])


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None
    stream: bool = True


@router.post("/chat")
async def chat(
    request: ChatRequest,
    settings: Settings = Depends(get_settings),
):
    """Send a message to the AI assistant.

    By default, streams the response via SSE for progressive rendering.
    Set stream=false for a complete JSON response.
    """
    engine = AssistantEngine(settings)

    if request.stream:
        session = engine.get_or_create_session(request.session_id)

        async def event_stream():
            yield f"data: {{\"type\": \"session\", \"session_id\": \"{session.session_id}\"}}\n\n"

            # Extract symbols and send tool usage events
            symbols = engine._extract_symbols(request.message)
            if symbols:
                syms_json = ", ".join(f'"{s}"' for s in symbols)
                yield f"data: {{\"type\": \"tools\", \"symbols\": [{syms_json}]}}\n\n"

            async for token in engine.stream_chat(request.message, session.session_id):
                escaped = token.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
                yield f"data: {{\"type\": \"token\", \"content\": \"{escaped}\"}}\n\n"

            yield f"data: {{\"type\": \"done\", \"entities\": {list(session.entities)}}}\n\n"

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
async def list_sessions(settings: Settings = Depends(get_settings)):
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
):
    """Delete an assistant session."""
    engine = AssistantEngine(settings)
    deleted = engine.delete_session(session_id)

    return {
        "success": deleted,
        "message": "Session deleted" if deleted else "Session not found",
    }

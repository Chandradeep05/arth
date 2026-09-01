"""
ARTH Phase 4 -- Persistent Conversations

Replaces in-memory _sessions dict in AssistantEngine.
AssistantEngine becomes stateless -- receives history from DB each call.
Only user/assistant messages persisted (no system prompts or tool internals).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.core.auth import UserContext, require_active_user
from app.core.logging import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/user/conversations", tags=["conversations"])

MAX_HISTORY_MESSAGES = 40  # ~8000 tokens, leaves room for system + response


class ConversationCreate(BaseModel):
    title: Optional[str] = "New Conversation"


class ConversationRename(BaseModel):
    title: str


class SendMessageRequest(BaseModel):
    content: str
    symbol_context: Optional[str] = None


@router.get("")
async def list_conversations(request: Request, user: UserContext = Depends(require_active_user)) -> list:
    db = request.state.db
    rows = await db.fetch(
        "SELECT id, title, message_count, created_at, updated_at FROM conversations WHERE user_id = $1 ORDER BY updated_at DESC LIMIT 50",
        user.user_id,
    )
    return [dict(row) for row in rows]


@router.post("")
async def create_conversation(body: ConversationCreate, request: Request, user: UserContext = Depends(require_active_user)) -> dict:
    db = request.state.db
    row = await db.fetchrow(
        "INSERT INTO conversations (user_id, title) VALUES ($1, $2) RETURNING id, title, message_count, created_at, updated_at",
        user.user_id, body.title or "New Conversation",
    )
    return dict(row)


@router.get("/{conversation_id}")
async def get_conversation(conversation_id: UUID, request: Request, user: UserContext = Depends(require_active_user)) -> dict:
    db = request.state.db
    conv = await db.fetchrow(
        "SELECT id, title, message_count, created_at, updated_at FROM conversations WHERE id = $1 AND user_id = $2",
        conversation_id, user.user_id,
    )
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found or not yours")
    messages = await db.fetch(
        "SELECT id, role, content, created_at FROM messages WHERE conversation_id = $1 ORDER BY created_at ASC",
        conversation_id,
    )
    return {**dict(conv), "messages": [dict(m) for m in messages]}


@router.put("/{conversation_id}")
async def rename_conversation(conversation_id: UUID, body: ConversationRename, request: Request, user: UserContext = Depends(require_active_user)) -> dict:
    db = request.state.db
    result = await db.execute(
        "UPDATE conversations SET title = $1 WHERE id = $2 AND user_id = $3",
        body.title, conversation_id, user.user_id,
    )
    if result == "UPDATE 0":
        raise HTTPException(status_code=404, detail="Conversation not found or not yours")
    return {"success": True}


@router.delete("/{conversation_id}")
async def delete_conversation(conversation_id: UUID, request: Request, user: UserContext = Depends(require_active_user)) -> dict:
    db = request.state.db
    result = await db.execute("DELETE FROM conversations WHERE id = $1 AND user_id = $2", conversation_id, user.user_id)
    if result == "DELETE 0":
        raise HTTPException(status_code=404, detail="Conversation not found or not yours")
    return {"success": True}


@router.post("/{conversation_id}/messages")
async def send_message(
    conversation_id: UUID,
    body: SendMessageRequest,
    request: Request,
    user: UserContext = Depends(require_active_user),
) -> dict:
    """Send message, load history from DB (replaces _sessions), persist response."""
    db = request.state.db
    conv = await db.fetchrow(
        "SELECT id FROM conversations WHERE id = $1 AND user_id = $2",
        conversation_id, user.user_id,
    )
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found or not yours")

    # Load recent history (token-budget aware: newest N messages, then reverse for chronological order)
    history_rows = await db.fetch(
        "SELECT role, content FROM messages WHERE conversation_id = $1 ORDER BY created_at DESC LIMIT $2",
        conversation_id, MAX_HISTORY_MESSAGES,
    )
    history = [{"role": r["role"], "content": r["content"]} for r in reversed(history_rows)]

    engine = request.app.state.assistant_engine
    try:
        ai_response = await engine.chat(
            user_message=body.content,
            history=history,
            symbol_context=body.symbol_context,
        )
    except Exception as e:
        logger.error("chat_failed", error=str(e), conversation_id=str(conversation_id))
        raise HTTPException(status_code=500, detail="AI response failed. Try again.")

    now = datetime.now(timezone.utc)
    async with db.transaction():
        await db.execute(
            "INSERT INTO messages (conversation_id, role, content, created_at) VALUES ($1, $2, $3, $4)",
            conversation_id, "user", body.content, now,
        )
        await db.execute(
            "INSERT INTO messages (conversation_id, role, content, created_at) VALUES ($1, $2, $3, $4)",
            conversation_id, "assistant", ai_response, now,
        )
        await db.execute(
            "UPDATE conversations SET message_count = message_count + 2, updated_at = $1 WHERE id = $2",
            now, conversation_id,
        )

    return {"role": "assistant", "content": ai_response, "conversation_id": str(conversation_id)}

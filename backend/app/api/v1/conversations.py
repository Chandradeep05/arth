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

from fastapi import APIRouter, Depends, HTTPException, Request, Query
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
    idempotency_key: Optional[str] = None


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
async def get_conversation(
    conversation_id: UUID,
    request: Request,
    limit: int = Query(default=20, le=100),
    cursor: Optional[UUID] = None,
    user: UserContext = Depends(require_active_user)
) -> dict:
    db = request.state.db
    conv = await db.fetchrow(
        "SELECT id, title, message_count, created_at, updated_at FROM conversations WHERE id = $1 AND user_id = $2",
        conversation_id, user.user_id,
    )
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found or not yours")
    
    if cursor:
        messages = await db.fetch(
            "SELECT id, role, content, created_at FROM messages "
            "WHERE conversation_id = $1 "
            "AND (created_at, id) > ((SELECT created_at FROM messages WHERE id = $2), $2) "
            "ORDER BY created_at ASC, id ASC LIMIT $3",
            conversation_id, cursor, limit,
        )
    else:
        messages = await db.fetch(
            "SELECT id, role, content, created_at FROM messages WHERE conversation_id = $1 ORDER BY created_at ASC LIMIT $2",
            conversation_id, limit,
        )
        
    items = [dict(m) for m in messages]
    next_cursor = items[-1]["id"] if items and len(items) == limit else None
    return {**dict(conv), "messages": items, "next_cursor": next_cursor}


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
    """Save a user message to the conversation. Does NOT call the LLM.

    LLM generation + streaming + assistant persistence happens via POST /assistant/chat.
    This endpoint saves only the user message for direct DB interaction.
    """
    db = request.state.db
    conv = await db.fetchrow(
        "SELECT id FROM conversations WHERE id = $1 AND user_id = $2",
        conversation_id, user.user_id,
    )
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found or not yours")

    now = datetime.now(timezone.utc)
    from datetime import timedelta
    assistant_ts = now + timedelta(microseconds=1)  # Guarantee ordering

    async with db.transaction():
        if body.idempotency_key:
            user_msg = await db.fetchrow(
                "INSERT INTO messages (conversation_id, role, content, created_at, idempotency_key) VALUES ($1, $2, $3, $4, $5) "
                "ON CONFLICT (conversation_id, idempotency_key) WHERE idempotency_key IS NOT NULL DO NOTHING RETURNING id",
                conversation_id, "user", body.content, now, body.idempotency_key
            )
            if not user_msg:
                # Duplicate — return existing assistant response (not user message)
                existing = await db.fetchrow(
                    "SELECT m.id, m.role, m.content, m.created_at FROM messages m "
                    "WHERE m.conversation_id = $1 AND m.role = 'assistant' "
                    "AND m.created_at >= (SELECT created_at FROM messages WHERE conversation_id = $1 AND idempotency_key = $2) "
                    "ORDER BY m.created_at ASC LIMIT 1",
                    conversation_id, body.idempotency_key
                )
                if existing:
                    return {"role": "assistant", "content": existing["content"], "conversation_id": str(conversation_id)}
                return {"role": "user", "content": body.content, "conversation_id": str(conversation_id), "duplicate": True}
        else:
            await db.execute(
                "INSERT INTO messages (conversation_id, role, content, created_at) VALUES ($1, $2, $3, $4)",
                conversation_id, "user", body.content, now,
            )

        await db.execute(
            "UPDATE conversations SET message_count = message_count + 1, updated_at = $1 WHERE id = $2",
            now, conversation_id,
        )

    return {"role": "user", "content": body.content, "conversation_id": str(conversation_id)}


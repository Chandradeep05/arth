"""
ARTH Phase 4 -- Saved Research (Immutable Snapshots)

Saved research is never updated in place.
Provenance fields (generated_at, data_as_of, engine_version) explain why
an old report may differ from current market data.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.core.auth import UserContext, require_active_user
from app.core.logging import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/user/research", tags=["saved_research"])


class SaveResearchRequest(BaseModel):
    symbol: str
    title: Optional[str] = None
    report_content: dict
    sources: list = []
    generated_at: Optional[datetime] = None
    data_as_of: Optional[datetime] = None
    engine_version: Optional[str] = "ARTH Research v1"


@router.get("/saved")
async def list_saved(request: Request, user: UserContext = Depends(require_active_user)) -> list:
    db = request.state.db
    rows = await db.fetch(
        "SELECT id, symbol, title, generated_at, data_as_of, engine_version, saved_at FROM saved_research WHERE user_id = $1 ORDER BY saved_at DESC LIMIT 100",
        user.user_id,
    )
    return [dict(row) for row in rows]


@router.post("/saved")
async def save_research(body: SaveResearchRequest, request: Request, user: UserContext = Depends(require_active_user)) -> dict:
    db = request.state.db
    row = await db.fetchrow(
        """INSERT INTO saved_research (user_id, symbol, title, report_content, sources, generated_at, data_as_of, engine_version)
           VALUES ($1, $2, $3, $4::jsonb, $5::jsonb, $6, $7, $8)
           RETURNING id, symbol, title, generated_at, data_as_of, engine_version, saved_at""",
        user.user_id, body.symbol.upper(),
        body.title or f"Research: {body.symbol.upper()}",
        json.dumps(body.report_content), json.dumps(body.sources),
        body.generated_at, body.data_as_of, body.engine_version,
    )
    return dict(row)


@router.get("/saved/{research_id}")
async def get_saved(research_id: UUID, request: Request, user: UserContext = Depends(require_active_user)) -> dict:
    db = request.state.db
    row = await db.fetchrow(
        "SELECT id, symbol, title, report_content, sources, generated_at, data_as_of, engine_version, saved_at FROM saved_research WHERE id = $1 AND user_id = $2",
        research_id, user.user_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Research not found or not yours")
    return dict(row)


@router.delete("/saved/{research_id}")
async def delete_saved(research_id: UUID, request: Request, user: UserContext = Depends(require_active_user)) -> dict:
    db = request.state.db
    result = await db.execute("DELETE FROM saved_research WHERE id = $1 AND user_id = $2", research_id, user.user_id)
    if result == "DELETE 0":
        raise HTTPException(status_code=404, detail="Research not found or not yours")
    return {"success": True}

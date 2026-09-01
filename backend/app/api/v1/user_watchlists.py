"""
ARTH Phase 4 -- Persistent User Watchlists

Ownership enforced in every query via WHERE user_id = $1.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, field_validator

from app.core.auth import UserContext, require_active_user
from app.core.logging import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/user/watchlists", tags=["watchlists"])


class WatchlistCreate(BaseModel):
    name: str = "My Watchlist"

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Watchlist name cannot be empty")
        return v[:64]


class WatchlistItemAdd(BaseModel):
    symbol: str
    notes: str = ""

    @field_validator("symbol")
    @classmethod
    def symbol_upper(cls, v: str) -> str:
        return v.strip().upper()


@router.get("")
async def list_watchlists(request: Request, user: UserContext = Depends(require_active_user)) -> list:
    db = request.state.db
    rows = await db.fetch(
        """SELECT w.id, w.name, w.created_at, COUNT(wi.id)::int AS item_count
           FROM watchlists w LEFT JOIN watchlist_items wi ON wi.watchlist_id = w.id
           WHERE w.user_id = $1 GROUP BY w.id ORDER BY w.created_at ASC""",
        user.user_id,
    )
    return [dict(row) for row in rows]


@router.post("")
async def create_watchlist(body: WatchlistCreate, request: Request, user: UserContext = Depends(require_active_user)) -> dict:
    db = request.state.db
    try:
        row = await db.fetchrow(
            "INSERT INTO watchlists (user_id, name) VALUES ($1, $2) RETURNING id, name, created_at",
            user.user_id, body.name,
        )
    except Exception as e:
        if "unique" in str(e).lower():
            raise HTTPException(status_code=409, detail=f"Watchlist named already exists")
        raise
    return dict(row)


@router.put("/{watchlist_id}")
async def rename_watchlist(watchlist_id: UUID, body: WatchlistCreate, request: Request, user: UserContext = Depends(require_active_user)) -> dict:
    db = request.state.db
    result = await db.execute("UPDATE watchlists SET name = $1 WHERE id = $2 AND user_id = $3", body.name, watchlist_id, user.user_id)
    if result == "UPDATE 0":
        raise HTTPException(status_code=404, detail="Watchlist not found or not yours")
    return {"success": True, "name": body.name}


@router.delete("/{watchlist_id}")
async def delete_watchlist(watchlist_id: UUID, request: Request, user: UserContext = Depends(require_active_user)) -> dict:
    db = request.state.db
    result = await db.execute("DELETE FROM watchlists WHERE id = $1 AND user_id = $2", watchlist_id, user.user_id)
    if result == "DELETE 0":
        raise HTTPException(status_code=404, detail="Watchlist not found or not yours")
    return {"success": True}


@router.get("/{watchlist_id}/items")
async def get_items(watchlist_id: UUID, request: Request, user: UserContext = Depends(require_active_user)) -> list:
    db = request.state.db
    rows = await db.fetch(
        """SELECT wi.id, wi.symbol, wi.notes, wi.added_at FROM watchlist_items wi
           JOIN watchlists w ON w.id = wi.watchlist_id
           WHERE wi.watchlist_id = $1 AND w.user_id = $2 ORDER BY wi.added_at ASC""",
        watchlist_id, user.user_id,
    )
    return [dict(row) for row in rows]


@router.post("/{watchlist_id}/items")
async def add_item(watchlist_id: UUID, body: WatchlistItemAdd, request: Request, user: UserContext = Depends(require_active_user)) -> dict:
    db = request.state.db
    owned = await db.fetchval("SELECT id FROM watchlists WHERE id = $1 AND user_id = $2", watchlist_id, user.user_id)
    if not owned:
        raise HTTPException(status_code=404, detail="Watchlist not found or not yours")
    row = await db.fetchrow(
        """INSERT INTO watchlist_items (watchlist_id, symbol, notes) VALUES ($1, $2, $3)
           ON CONFLICT (watchlist_id, symbol) DO UPDATE SET notes = EXCLUDED.notes
           RETURNING id, symbol, notes, added_at""",
        watchlist_id, body.symbol, body.notes,
    )
    return dict(row)


@router.delete("/{watchlist_id}/items/{symbol}")
async def remove_item(watchlist_id: UUID, symbol: str, request: Request, user: UserContext = Depends(require_active_user)) -> dict:
    db = request.state.db
    result = await db.execute(
        """DELETE FROM watchlist_items WHERE watchlist_id = $1 AND symbol = $2
           AND watchlist_id IN (SELECT id FROM watchlists WHERE user_id = $3)""",
        watchlist_id, symbol.upper(), user.user_id,
    )
    if result == "DELETE 0":
        raise HTTPException(status_code=404, detail="Item not found")
    return {"success": True}

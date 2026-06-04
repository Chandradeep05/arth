"""
Pydantic schemas for watchlist API requests.

WatchlistBatchRequest is the request body for POST /watchlist/batch.
Enforces a maximum of 20 symbols per batch to prevent abuse and
keep response times reasonable.
"""

from __future__ import annotations

from typing import List

from pydantic import BaseModel, field_validator


class WatchlistBatchRequest(BaseModel):
    """Request body for batch watchlist data fetching."""

    symbols: List[str]

    @field_validator("symbols")
    @classmethod
    def limit_symbols(cls, v: List[str]) -> List[str]:
        """Enforce a maximum of 20 symbols per batch request."""
        if len(v) > 20:
            raise ValueError("Maximum 20 symbols per batch request")
        if len(v) == 0:
            raise ValueError("At least one symbol is required")
        return [s.upper() for s in v]

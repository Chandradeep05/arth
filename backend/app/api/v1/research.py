"""
AI Research API endpoints.

Provides:
- POST /research/generate/{symbol} — Generate research report (SSE streaming)
- GET /research/report/{symbol} — Get cached report
- POST /research/index/{symbol} — Index documents for RAG (Phase 2)
- GET /research/sources/{symbol} — List indexed documents (Phase 2)
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from app.config import Settings, get_settings
from app.core.exceptions import SymbolNotFoundError
from app.core.logging import get_logger
from app.data.cache import CacheManager
from app.dependencies import get_redis
from app.engines.research.engine import ResearchEngine
from app.models.schemas.market import FreshnessMetadata

logger = get_logger(__name__)
router = APIRouter(prefix="/research", tags=["research"])


@router.post("/generate/{symbol}")
async def generate_research(
    symbol: str,
    depth: str = Query(default="standard", description="quick, standard, or deep"),
    stream: bool = Query(default=True, description="Stream response via SSE"),
    redis=Depends(get_redis),
    settings: Settings = Depends(get_settings),
):
    """
    Generate an AI research report for a stock symbol.

    Streams the response via Server-Sent Events for progressive rendering.
    depth=deep uses RAG for cited reports (requires indexing first).
    """
    engine = ResearchEngine(settings)

    if stream:
        async def event_stream():
            yield f"data: {{\"type\": \"start\", \"symbol\": \"{symbol.upper()}\"}}\n\n"
            if depth == "deep":
                gen = engine.stream_deep_research(symbol)
            else:
                gen = engine.stream_report(symbol, depth)
            async for token in gen:
                # Escape for SSE
                escaped = token.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
                yield f"data: {{\"type\": \"token\", \"content\": \"{escaped}\"}}\n\n"
            yield f"data: {{\"type\": \"done\"}}\n\n"

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
        # Non-streaming: return complete report
        cache = CacheManager(redis)
        try:
            if depth == "deep":
                report = await engine.generate_deep_research(symbol, cache)
            else:
                report = await engine.generate_report(symbol, depth, cache)
        except Exception as e:
            logger.error("research_generation_failed", symbol=symbol, error=str(e))
            return {
                "success": False,
                "message": f"Research generation failed: {str(e)}. Ensure GROQ_API_KEY is configured.",
            }

        if report.get("error"):
            return {
                "success": False,
                "message": report.get("message"),
            }

        return {
            "success": True,
            "data": report,
            "freshness": FreshnessMetadata(
                source="groq_llm",
                timestamp=datetime.now(timezone.utc),
                is_stale=False,
                delay_label="AI-generated (deep)" if depth == "deep" else "AI-generated",
                cache_hit=False,
            ).model_dump(),
        }


@router.get("/report/{symbol}")
async def get_cached_report(
    symbol: str,
    redis=Depends(get_redis),
):
    """Get a previously generated research report from cache."""
    cache = CacheManager(redis)
    report = await cache.get(cache.research_key(symbol))

    if report is None:
        return {
            "success": False,
            "message": f"No cached report for {symbol}. Generate one first.",
        }

    return {
        "success": True,
        "data": report,
        "freshness": FreshnessMetadata(
            source="cache",
            timestamp=datetime.now(timezone.utc),
            is_stale=False,
            delay_label="Cached",
            cache_hit=True,
        ).model_dump(),
    }


# ── RAG Endpoints (Phase 2) ─────────────────────────────────────

@router.post("/index/{symbol}")
async def index_company(symbol: str):
    """Trigger document ingestion for RAG-powered deep research.

    Fetches company info, financials, and news from Yahoo Finance,
    chunks the text, and indexes it in the in-memory vector store.
    """
    from app.engines.rag.document_processor import DocumentProcessor

    processor = DocumentProcessor()
    try:
        result = await processor.index_company(symbol)
    except Exception as e:
        logger.error("index_company_failed", symbol=symbol, error=str(e))
        return {
            "success": False,
            "message": f"Document indexing failed: {str(e)}",
        }

    return {
        "success": True,
        "data": result,
    }


@router.get("/sources/{symbol}")
async def list_sources(symbol: str):
    """List indexed documents for a company."""
    from app.engines.rag.vector_store import vector_store

    sources = vector_store.list_sources(symbol)
    count = vector_store.get_document_count(symbol)

    return {
        "success": True,
        "data": {
            "symbol": symbol.upper(),
            "document_count": count,
            "sources": sources,
            "has_documents": count > 0,
        },
    }


"""
AI Research Engine (Module 02 — Phase 1 Basic).

Generates company research reports using:
1. Market data fundamentals (via MarketDataProvider)
2. Technical indicators (computed)
3. Groq LLM (for analysis generation)

All numerical data is fetched from market data providers FIRST, then injected
into the LLM prompt. The LLM never generates numbers from memory.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Dict, Optional

from app.config import Settings, get_settings
from app.core.logging import get_logger
from app.data.market_data_provider import market_data
from app.data.cache import CacheManager
from app.engines.market.indicators import compute_indicators
from app.engines.research.prompts import (
    RESEARCH_SYSTEM_PROMPT,
    DEEP_RESEARCH_SYSTEM_PROMPT,
    build_quick_summary_prompt,
    build_research_prompt,
    build_deep_research_prompt,
)
from app.engines.rag.retriever import RAGRetriever
from app.llm.base import LLMConfig, LLMMessage
from app.llm.groq_client import GroqClient

logger = get_logger(__name__)


class ResearchEngine:
    """AI-powered company research engine."""

    def __init__(self, settings: Settings | None = None):
        self._settings = settings or get_settings()
        self._data = market_data
        self._llm: GroqClient | None = None

        # Initialize LLM client
        api_key = self._settings.groq_api_key or ""
        if api_key and not api_key.startswith("your_"):
            try:
                self._llm = GroqClient(
                    api_key=api_key,
                    default_model=self._settings.groq_model,
                )
            except Exception as e:
                logger.warning("groq_client_init_failed", error=str(e))

    async def generate_report(
        self,
        symbol: str,
        depth: str = "standard",
        cache: CacheManager | None = None,
    ) -> Dict[str, Any]:
        """Generate a complete research report (non-streaming)."""
        if not self._llm:
            return {
                "error": True,
                "message": "LLM not configured. Set GROQ_API_KEY in environment.",
            }

        # Step 1: Fetch real market data
        info_result = await self._data.get_company_info(symbol)
        company_info = info_result.data if info_result.available else None
        if not company_info:
            return {
                "error": True,
                "message": f"Could not fetch data for {symbol}",
            }

        metrics = company_info.get("metrics", {})

        # Step 2: Compute technical indicators
        indicators = None
        history_result = await self._data.get_history(symbol, period="3mo", interval="1d")
        ohlcv_result = history_result.data if history_result.available else None
        # get_ohlcv returns {"bars": [...], "_validation": {...}} or a plain list
        if ohlcv_result is not None:
            # history_result.data is a normalized DataFrame from MarketDataProvider
            # compute_indicators expects a list of bar dicts, so convert if DataFrame
            if hasattr(ohlcv_result, 'to_dict'):
                ohlcv_df = ohlcv_result.rename(columns=str.lower).reset_index()
                ohlcv = ohlcv_df.rename(columns={'datetime': 'date'}).to_dict('records')
            elif isinstance(ohlcv_result, dict):
                ohlcv = ohlcv_result.get("bars", ohlcv_result)
            else:
                ohlcv = ohlcv_result
            if ohlcv and isinstance(ohlcv, list):
                indicators = compute_indicators(ohlcv)

        # Step 3: Build prompt with real data
        if depth == "quick":
            user_prompt = build_quick_summary_prompt(symbol, company_info, metrics)
        else:
            user_prompt = build_research_prompt(symbol, company_info, metrics, indicators)

        # Step 4: Generate analysis via LLM
        messages = [
            LLMMessage(role="system", content=RESEARCH_SYSTEM_PROMPT),
            LLMMessage(role="user", content=user_prompt),
        ]

        config = LLMConfig(
            max_tokens=2048 if depth == "quick" else 4096,
            temperature=0.3,
        )

        response = await self._llm.generate(messages, config)

        # Step 5: Build structured report
        report = {
            "symbol": symbol.upper(),
            "company_name": company_info.get("name", symbol),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "report_content": response.content,
            "confidence_score": 65.0,  # Base confidence — Phase 2 will compute this dynamically
            "data_sources": [self._data.get_source_label(symbol)],
            "llm_provider": response.provider,
            "llm_model": response.model,
            "tokens_used": response.tokens_used,
            "latency_ms": round(response.latency_ms, 2),
            "metrics": metrics,
            "indicators": indicators,
            "disclaimer": (
                "⚠ This is AI-generated analysis for informational purposes only. "
                "This is NOT financial advice. Always consult a qualified financial advisor."
            ),
        }

        # Cache the report
        if cache:
            await cache.set(
                cache.research_key(symbol),
                report,
                ttl=3600,  # 1 hour
            )

        logger.info(
            "research_report_generated",
            symbol=symbol,
            depth=depth,
            tokens=response.tokens_used,
            latency_ms=round(response.latency_ms, 2),
        )

        return report

    async def stream_report(
        self,
        symbol: str,
        depth: str = "standard",
    ) -> AsyncGenerator[str, None]:
        """Stream a research report token-by-token for SSE."""
        if not self._llm:
            yield "Error: LLM not configured. Set GROQ_API_KEY in environment."
            return

        # Fetch real data
        info_result = await self._data.get_company_info(symbol)
        company_info = info_result.data if info_result.available else None
        if not company_info:
            yield f"Error: Could not fetch data for {symbol}"
            return

        metrics = company_info.get("metrics", {})

        # Compute indicators
        indicators = None
        history_result = await self._data.get_history(symbol, period="3mo", interval="1d")
        ohlcv_result = history_result.data if history_result.available else None
        if ohlcv_result is not None:
            if hasattr(ohlcv_result, 'to_dict'):
                ohlcv_df = ohlcv_result.rename(columns=str.lower).reset_index()
                ohlcv = ohlcv_df.rename(columns={'datetime': 'date'}).to_dict('records')
            elif isinstance(ohlcv_result, dict):
                ohlcv = ohlcv_result.get("bars", ohlcv_result)
            else:
                ohlcv = ohlcv_result
            if ohlcv and isinstance(ohlcv, list):
                indicators = compute_indicators(ohlcv)

        # Build prompt
        if depth == "quick":
            user_prompt = build_quick_summary_prompt(symbol, company_info, metrics)
        else:
            user_prompt = build_research_prompt(symbol, company_info, metrics, indicators)

        messages = [
            LLMMessage(role="system", content=RESEARCH_SYSTEM_PROMPT),
            LLMMessage(role="user", content=user_prompt),
        ]

        config = LLMConfig(
            max_tokens=2048 if depth == "quick" else 4096,
            temperature=0.3,
        )

        # Stream tokens
        async for token in self._llm.stream(messages, config):
            yield token

    # ── Deep Research (RAG-powered, Phase 2) ────────────────────

    async def generate_deep_research(
        self,
        symbol: str,
        cache: CacheManager | None = None,
    ) -> Dict[str, Any]:
        """Generate a RAG-powered research report with citations.

        Requires documents to be indexed first via DocumentProcessor.
        """
        if not self._llm:
            return {
                "error": True,
                "message": "LLM not configured. Set GROQ_API_KEY in environment.",
            }

        # Check vector store
        retriever = RAGRetriever()
        from app.engines.rag.vector_store import vector_store

        if not vector_store.has_documents(symbol):
            return {
                "error": True,
                "message": (
                    f"No documents indexed for {symbol}. "
                    f"Call POST /research/index/{symbol} first."
                ),
            }

        # Step 1: Fetch real data (same as standard)
        info_result = await self._data.get_company_info(symbol)
        company_info = info_result.data if info_result.available else None
        if not company_info:
            return {"error": True, "message": f"Could not fetch data for {symbol}"}

        metrics = company_info.get("metrics", {})

        # Step 2: Compute indicators
        indicators = None
        history_result = await self._data.get_history(symbol, period="3mo", interval="1d")
        if history_result.available and history_result.data is not None:
            ohlcv_data = history_result.data
            if hasattr(ohlcv_data, 'to_dict'):
                ohlcv_df = ohlcv_data.rename(columns=str.lower).reset_index()
                bars = ohlcv_df.rename(columns={'datetime': 'date'}).to_dict('records')
            elif isinstance(ohlcv_data, dict):
                bars = ohlcv_data.get("bars", ohlcv_data)
            else:
                bars = ohlcv_data
            if bars and isinstance(bars, list):
                indicators = compute_indicators(bars)

        # Step 3: Retrieve RAG context
        rag_result = retriever.retrieve_context(
            symbol=symbol,
            query=f"financial analysis research report for {symbol}",
            max_chunks=8,
        )

        # Step 4: Build RAG-aware prompt
        user_prompt = build_deep_research_prompt(
            symbol, company_info, metrics, indicators, rag_result["context_text"]
        )

        messages = [
            LLMMessage(role="system", content=DEEP_RESEARCH_SYSTEM_PROMPT),
            LLMMessage(role="user", content=user_prompt),
        ]

        config = LLMConfig(max_tokens=4096, temperature=0.3)
        response = await self._llm.generate(messages, config)

        # Step 5: Build report with sources
        report = {
            "symbol": symbol.upper(),
            "company_name": company_info.get("name", symbol),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "report_content": response.content,
            "report_type": "deep",
            "confidence_score": 75.0,  # Higher confidence with RAG
            "data_sources": [self._data.get_source_label(symbol)] + [
                s["source"] for s in rag_result["sources"]
            ],
            "sources": rag_result["sources"],
            "chunks_retrieved": rag_result["chunks_retrieved"],
            "llm_provider": response.provider,
            "llm_model": response.model,
            "tokens_used": response.tokens_used,
            "latency_ms": round(response.latency_ms, 2),
            "metrics": metrics,
            "indicators": indicators,
            "disclaimer": (
                "⚠ This is AI-generated analysis for informational purposes only. "
                "This is NOT financial advice. Always consult a qualified financial advisor."
            ),
        }

        if cache:
            await cache.set(cache.research_key(symbol), report, ttl=3600)

        logger.info(
            "deep_research_generated",
            symbol=symbol,
            sources=rag_result["chunks_retrieved"],
            tokens=response.tokens_used,
        )

        return report

    async def stream_deep_research(
        self,
        symbol: str,
    ) -> AsyncGenerator[str, None]:
        """Stream a RAG-powered research report token-by-token."""
        if not self._llm:
            yield "Error: LLM not configured. Set GROQ_API_KEY in environment."
            return

        retriever = RAGRetriever()
        from app.engines.rag.vector_store import vector_store

        if not vector_store.has_documents(symbol):
            yield f"Error: No documents indexed for {symbol}. Index documents first."
            return

        # Fetch data
        info_result = await self._data.get_company_info(symbol)
        company_info = info_result.data if info_result.available else None
        if not company_info:
            yield f"Error: Could not fetch data for {symbol}"
            return

        metrics = company_info.get("metrics", {})

        indicators = None
        history_result = await self._data.get_history(symbol, period="3mo", interval="1d")
        if history_result.available and history_result.data is not None:
            ohlcv_data = history_result.data
            if hasattr(ohlcv_data, 'to_dict'):
                ohlcv_df = ohlcv_data.rename(columns=str.lower).reset_index()
                bars = ohlcv_df.rename(columns={'datetime': 'date'}).to_dict('records')
            elif isinstance(ohlcv_data, dict):
                bars = ohlcv_data.get("bars", ohlcv_data)
            else:
                bars = ohlcv_data
            if bars and isinstance(bars, list):
                indicators = compute_indicators(bars)

        # RAG context
        rag_result = retriever.retrieve_context(
            symbol=symbol,
            query=f"financial analysis research report for {symbol}",
        )

        user_prompt = build_deep_research_prompt(
            symbol, company_info, metrics, indicators, rag_result["context_text"]
        )

        messages = [
            LLMMessage(role="system", content=DEEP_RESEARCH_SYSTEM_PROMPT),
            LLMMessage(role="user", content=user_prompt),
        ]

        config = LLMConfig(max_tokens=4096, temperature=0.3)

        async for token in self._llm.stream(messages, config):
            yield token


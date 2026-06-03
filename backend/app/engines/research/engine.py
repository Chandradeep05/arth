"""
AI Research Engine (Module 02 — Phase 1 Basic).

Generates company research reports using:
1. Yahoo Finance fundamentals (real data)
2. Technical indicators (computed)
3. Groq LLM (for analysis generation)

All numerical data is fetched from Yahoo Finance FIRST, then injected
into the LLM prompt. The LLM never generates numbers from memory.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Dict, Optional

from app.config import Settings, get_settings
from app.core.logging import get_logger
from app.data.adapters.yahoo import YahooFinanceAdapter
from app.data.cache import CacheManager
from app.engines.market.indicators import compute_indicators
from app.engines.research.prompts import (
    RESEARCH_SYSTEM_PROMPT,
    build_quick_summary_prompt,
    build_research_prompt,
)
from app.llm.base import LLMConfig, LLMMessage
from app.llm.groq_client import GroqClient

logger = get_logger(__name__)


class ResearchEngine:
    """AI-powered company research engine."""

    def __init__(self, settings: Settings | None = None):
        self._settings = settings or get_settings()
        self._yahoo = YahooFinanceAdapter()
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

        # Step 1: Fetch real data from Yahoo Finance
        company_info = await self._yahoo.get_company_info(symbol)
        if not company_info:
            return {
                "error": True,
                "message": f"Could not fetch data for {symbol}",
            }

        metrics = company_info.get("metrics", {})

        # Step 2: Compute technical indicators
        indicators = None
        ohlcv = await self._yahoo.get_ohlcv(symbol, period="3mo", interval="1d")
        if ohlcv:
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
            "data_sources": ["Yahoo Finance"],
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
        company_info = await self._yahoo.get_company_info(symbol)
        if not company_info:
            yield f"Error: Could not fetch data for {symbol}"
            return

        metrics = company_info.get("metrics", {})

        # Compute indicators
        indicators = None
        ohlcv = await self._yahoo.get_ohlcv(symbol, period="3mo", interval="1d")
        if ohlcv:
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

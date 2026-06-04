"""
AI Assistant Engine (Phase 2).

A conversational financial assistant with tool routing.
Uses Groq LLM with a system prompt that routes queries to internal tools:
- analyze: Full stock analysis
- compare: Compare two stocks
- risk: Risk assessment
- sentiment: Sentiment analysis
- financials: Financial statements
- quote: Quick price check

The assistant maintains ephemeral in-memory sessions with entity tracking.
"""

from __future__ import annotations

import time
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Dict, List, Optional

from app.config import Settings, get_settings
from app.core.logging import get_logger
from app.data.adapters.yahoo import YahooFinanceAdapter
from app.data.cache import CacheManager
from app.llm.base import LLMConfig, LLMMessage, LLMResponse
from app.llm.groq_client import GroqClient

logger = get_logger(__name__)


ASSISTANT_SYSTEM_PROMPT = """You are ARTH, an AI financial research assistant. You help users analyze Indian and US stocks with data-driven insights.

CONTEXT: You have access to real-time financial data from Yahoo Finance. When the user asks about a specific stock, the system will inject real-time data into the conversation for you to analyze.

YOUR PERSONALITY:
- Professional but conversational
- Data-driven — always reference specific numbers
- Honest about limitations — you use delayed data (~15s), not live
- Cautious — never give buy/sell recommendations

RESPONSE STYLE:
- Keep responses concise (150-300 words unless deep analysis is requested)
- Use bullet points for key metrics
- Bold important numbers with **value**
- Always mention the data source and delay
- End with a brief risk note

TOOLS AVAILABLE (injected by system):
When the user mentions a stock symbol or company name, the system automatically provides:
- Current price, change%, volume
- Key metrics (P/E, market cap, margins)
- Technical signals if available
- Recent sentiment if available

CRITICAL RULES:
1. ONLY use data provided in the [MARKET DATA] sections. Never make up numbers.
2. Use probabilistic language: "suggests", "indicates", "approximately"
3. NEVER say: "buy", "sell", "guaranteed", "will go up/down"
4. Always include: "This is not financial advice"
5. If data is missing, say so honestly

⚠ DISCLAIMER: All analysis is AI-generated and for informational purposes only.
"""


class AssistantSession:
    """Ephemeral in-memory session for a conversation."""

    def __init__(self, session_id: str | None = None):
        self.session_id = session_id or str(uuid.uuid4())[:8]
        self.messages: List[Dict[str, str]] = []
        self.entities: List[str] = []  # Tracked stock symbols
        self.created_at = datetime.now(timezone.utc)
        self.last_active = datetime.now(timezone.utc)
        self.tool_calls: List[str] = []

    def add_message(self, role: str, content: str) -> None:
        self.messages.append({"role": role, "content": content})
        self.last_active = datetime.now(timezone.utc)
        # Keep only last 20 messages to avoid token overflow
        if len(self.messages) > 20:
            # Keep system + last 18 exchanges
            self.messages = self.messages[:1] + self.messages[-18:]

    def add_entity(self, symbol: str) -> None:
        sym = symbol.upper()
        if sym not in self.entities:
            self.entities.append(sym)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "message_count": len(self.messages),
            "entities": self.entities,
            "created_at": self.created_at.isoformat(),
            "last_active": self.last_active.isoformat(),
            "tool_calls": self.tool_calls[-10:],
        }


class AssistantEngine:
    """Conversational financial assistant with tool routing."""

    # In-memory session store (ephemeral — cleared on restart)
    _sessions: Dict[str, AssistantSession] = {}

    def __init__(self, settings: Settings | None = None):
        self._settings = settings or get_settings()
        self._yahoo = YahooFinanceAdapter()
        self._llm: GroqClient | None = None

        api_key = self._settings.groq_api_key or ""
        if api_key and not api_key.startswith("your_"):
            try:
                self._llm = GroqClient(
                    api_key=api_key,
                    default_model=self._settings.groq_model,
                )
            except Exception as e:
                logger.warning("assistant_llm_init_failed", error=str(e))

    # ── Session management ──────────────────────────────────────

    def get_or_create_session(self, session_id: str | None = None) -> AssistantSession:
        if session_id and session_id in self._sessions:
            return self._sessions[session_id]
        session = AssistantSession(session_id)
        self._sessions[session.session_id] = session
        return session

    def get_session(self, session_id: str) -> AssistantSession | None:
        return self._sessions.get(session_id)

    def list_sessions(self) -> List[Dict[str, Any]]:
        return [s.to_dict() for s in self._sessions.values()]

    def delete_session(self, session_id: str) -> bool:
        return self._sessions.pop(session_id, None) is not None

    # ── Tool routing ────────────────────────────────────────────

    def _extract_symbols(self, message: str) -> List[str]:
        """Extract stock symbols from user message."""
        import re
        symbols = []
        # Match patterns like RELIANCE.NS, TCS.BO, AAPL
        pattern = r'\b([A-Z]{2,15}(?:\.NS|\.BO)?)\b'
        candidates = re.findall(pattern, message.upper())

        # Filter out common English words
        stop_words = {
            "THE", "AND", "FOR", "ARE", "BUT", "NOT", "YOU", "ALL",
            "HER", "WAS", "ONE", "OUR", "OUT", "HAS", "HIS", "HOW",
            "ITS", "LET", "MAY", "NEW", "NOW", "OLD", "SEE", "WAY",
            "WHO", "DID", "GET", "HIM", "HIT", "PUT", "SAY", "SHE",
            "TOO", "USE", "WHY", "CAN", "HAD", "HER", "ANY", "ASK",
            "BAD", "BIG", "BIT", "DAY", "END", "FAR", "FEW", "GOT",
            "WHY", "WHAT", "WITH", "WILL", "WOULD", "TELL", "ABOUT",
            "THINK", "COULD", "ALSO", "THAN", "VERY", "BEEN", "SOME",
            "FROM", "HAVE", "THIS", "THAT", "THEY", "EACH", "MAKE",
            "LIKE", "LONG", "LOOK", "MANY", "MOST", "MUCH", "MUST",
            "NAME", "ONLY", "OVER", "SUCH", "TAKE", "THEM", "THEN",
            "WELL", "WHEN", "HERE", "JUST", "KNOW", "LAST", "HELP",
            "DOES", "GIVE", "GOOD", "HIGH", "LOW", "RISK", "STOCK",
            "MARKET", "PRICE", "COMPARE", "ANALYZE", "ANALYSIS",
            "SHOW", "TODAY", "BUY", "SELL", "HOLD",
        }

        for sym in candidates:
            if sym not in stop_words and len(sym) >= 2:
                symbols.append(sym)

        return symbols[:3]  # Max 3 symbols per query

    async def _fetch_market_data(self, symbol: str) -> str:
        """Fetch real market data for injection into the LLM context."""
        parts = [f"\n[MARKET DATA for {symbol}]"]

        # Quote
        try:
            quote = await self._yahoo.get_quote(symbol)
            if quote:
                quote.pop("_validation", None)
                parts.append(
                    f"Price: {quote.get('price', 'N/A')} | "
                    f"Change: {quote.get('change', 0)} ({quote.get('change_percent', 0):.2f}%) | "
                    f"Volume: {quote.get('volume', 'N/A')} | "
                    f"High: {quote.get('high', 'N/A')} | Low: {quote.get('low', 'N/A')} | "
                    f"Market Cap: {quote.get('market_cap', 'N/A')} | "
                    f"P/E: {quote.get('pe_ratio', 'N/A')}"
                )
        except Exception as e:
            parts.append(f"Quote: unavailable ({e})")

        # Company info (lightweight)
        try:
            info = await self._yahoo.get_company_info(symbol)
            if info:
                parts.append(
                    f"Company: {info.get('name', symbol)} | "
                    f"Sector: {info.get('sector', 'N/A')} | "
                    f"Industry: {info.get('industry', 'N/A')}"
                )
                metrics = info.get("metrics", {})
                if metrics:
                    parts.append(
                        f"ROE: {metrics.get('roe', 'N/A')} | "
                        f"Revenue Growth: {metrics.get('revenue_growth', 'N/A')} | "
                        f"Profit Margin: {metrics.get('profit_margin', 'N/A')} | "
                        f"D/E: {metrics.get('debt_to_equity', 'N/A')}"
                    )
        except Exception:
            pass

        parts.append("[END MARKET DATA]\n")
        return "\n".join(parts)

    # ── Chat ────────────────────────────────────────────────────

    async def chat(
        self,
        message: str,
        session_id: str | None = None,
    ) -> Dict[str, Any]:
        """Process a chat message and return a complete response."""
        if not self._llm:
            return {
                "error": True,
                "message": "LLM not configured. Set GROQ_API_KEY.",
            }

        session = self.get_or_create_session(session_id)

        # Extract and track symbols
        symbols = self._extract_symbols(message)
        tools_used = []

        # Build context with real market data
        data_context = ""
        for sym in symbols:
            session.add_entity(sym)
            data_context += await self._fetch_market_data(sym)
            tools_used.append(f"quote:{sym}")

        # Build augmented user message
        augmented_message = message
        if data_context:
            augmented_message = f"{message}\n\n{data_context}"

        session.add_message("user", message)  # Store original (no data injection)

        # Build LLM messages
        llm_messages = [
            LLMMessage(role="system", content=ASSISTANT_SYSTEM_PROMPT),
        ]
        # Add conversation history (last N messages)
        for msg in session.messages[-12:]:
            llm_messages.append(LLMMessage(role=msg["role"], content=msg["content"]))
        # Replace last user message with augmented version
        llm_messages[-1] = LLMMessage(role="user", content=augmented_message)

        config = LLMConfig(max_tokens=1024, temperature=0.4)

        start = time.monotonic()
        response = await self._llm.generate(llm_messages, config)
        latency = (time.monotonic() - start) * 1000

        # Store assistant response
        session.add_message("assistant", response.content)
        session.tool_calls.extend(tools_used)

        return {
            "session_id": session.session_id,
            "response": response.content,
            "tools_used": tools_used,
            "entities": session.entities,
            "tokens_used": response.tokens_used,
            "latency_ms": round(latency, 2),
        }

    async def stream_chat(
        self,
        message: str,
        session_id: str | None = None,
    ) -> AsyncGenerator[str, None]:
        """Stream a chat response token-by-token."""
        if not self._llm:
            yield "Error: LLM not configured. Set GROQ_API_KEY."
            return

        session = self.get_or_create_session(session_id)

        # Extract symbols and fetch data
        symbols = self._extract_symbols(message)
        data_context = ""
        for sym in symbols:
            session.add_entity(sym)
            data_context += await self._fetch_market_data(sym)
            session.tool_calls.append(f"quote:{sym}")

        augmented_message = message
        if data_context:
            augmented_message = f"{message}\n\n{data_context}"

        session.add_message("user", message)

        llm_messages = [
            LLMMessage(role="system", content=ASSISTANT_SYSTEM_PROMPT),
        ]
        for msg in session.messages[-12:]:
            llm_messages.append(LLMMessage(role=msg["role"], content=msg["content"]))
        llm_messages[-1] = LLMMessage(role="user", content=augmented_message)

        config = LLMConfig(max_tokens=1024, temperature=0.4)

        full_response = ""
        async for token in self._llm.stream(llm_messages, config):
            full_response += token
            yield token

        session.add_message("assistant", full_response)

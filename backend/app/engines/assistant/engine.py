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
from app.data.market_data_provider import market_data
from app.data.cache import CacheManager
from app.llm.base import LLMConfig, LLMMessage, LLMResponse
from app.llm.groq_client import GroqClient

logger = get_logger(__name__)


ASSISTANT_SYSTEM_PROMPT = """You are ARTH, an AI financial research assistant. You help users analyze Indian and US stocks with data-driven insights.

CONTEXT: You have access to financial data from MarketDataProvider (Twelve Data, Finnhub, FMP, NSE India). When the user asks about a specific stock, the system will inject market data into the conversation for you to analyze.

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
        self._data = market_data
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
    SESSION_TTL_SECONDS = 1800  # 30 minutes of inactivity → evict
    MAX_SESSIONS = 50           # Safety cap for Render 512MB RAM

    def _evict_stale_sessions(self) -> None:
        """Remove sessions inactive for longer than SESSION_TTL_SECONDS."""
        now = datetime.now(timezone.utc)
        stale = [
            sid for sid, session in self._sessions.items()
            if (now - session.last_active).total_seconds() > self.SESSION_TTL_SECONDS
        ]
        for sid in stale:
            del self._sessions[sid]
        if stale:
            logger.info("sessions_evicted", count=len(stale), remaining=len(self._sessions))

    def get_or_create_session(self, session_id: str | None = None) -> AssistantSession:
        # Sweep stale sessions on every creation
        self._evict_stale_sessions()

        if session_id and session_id in self._sessions:
            return self._sessions[session_id]

        # Cap total sessions to prevent OOM
        if len(self._sessions) >= self.MAX_SESSIONS:
            # Evict oldest session
            oldest_id = min(self._sessions, key=lambda s: self._sessions[s].last_active)
            del self._sessions[oldest_id]
            logger.warning("session_cap_eviction", evicted=oldest_id, cap=self.MAX_SESSIONS)

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
        """Extract stock symbols from user message.

        Uses a combination of regex matching, an expanded stop-word list,
        and structural heuristics to avoid false positives like 'DOING',
        'SEEN', 'HELD' etc. that are valid English words matching [A-Z]{1,5}.
        """
        import re
        symbols = []
        # Match explicit Indian symbols (e.g. TCS.NS) FIRST, then 1-5 char uppercase US tickers
        # Indian pattern must come first so TCS.NS matches as TCS.NS, not just TCS
        pattern = r'\b([A-Z]{2,15}\.(?:NS|BO)|[A-Z]{1,5})\b'
        candidates = re.findall(pattern, message.upper())

        stop_words = {
            # 2-letter common words
            "AM", "AN", "AS", "AT", "BE", "BY", "DO", "GO", "HE",
            "IF", "IN", "IS", "IT", "ME", "MY", "NO", "OF", "ON",
            "OR", "SO", "TO", "UP", "US", "VS", "WE",
            # 3-letter common words
            "ADD", "AGO", "ALL", "AND", "ANY", "ARE", "ASK", "BAD",
            "BIG", "BIT", "BUT", "CAN", "DAY", "DID", "END", "FAR",
            "FEW", "FOR", "GET", "GOT", "HAD", "HAS", "HER", "HIM",
            "HIS", "HOW", "ITS", "LET", "MAY", "MEN", "NEW", "NOT",
            "NOW", "OLD", "ONE", "OUR", "OUT", "OWN", "PUT", "RUN",
            "SAY", "SHE", "THE", "TOO", "TRY", "TWO", "USE", "WAY",
            "WHO", "WHY", "WON", "YES", "YET", "YOU", "SET", "TOP",
            "LOW", "RED", "NET", "OWE", "PAY", "RAW", "SEE", "SAW",
            # 4-5 letter common words & verbs
            "ALSO", "BEEN", "BEST", "BOTH", "COME", "DOES", "DONE",
            "DOWN", "EACH", "EVEN", "FIND", "FROM", "GIVE", "GONE",
            "GOOD", "HAVE", "HERE", "HIGH", "HOLD", "JUST", "KEEP",
            "KNOW", "LAST", "LIKE", "LONG", "LOOK", "MADE", "MAKE",
            "MANY", "MORE", "MOST", "MUCH", "MUST", "NAME", "NEXT",
            "ONLY", "OVER", "SEEM", "SHOW", "SOME", "SUCH", "TAKE",
            "TELL", "THAN", "THAT", "THEM", "THEN", "THEY", "THIS",
            "VERY", "WANT", "WELL", "WENT", "WERE", "WHAT", "WHEN",
            "WILL", "WITH", "WORK", "YEAR", "GOING", "WHICH", "BETTER",
            "EXPECT", "FUTURE", "SHOULD", "PERFORM", "TARGET",
            # Common verbs/words that are 2-5 chars and match ticker pattern
            # These caused false positives in production (e.g. "DOING" parsed as ticker)
            "DOING", "BEING", "SEEN", "HELD", "SOLD", "TOLD", "SAID",
            "USED", "GAVE", "TOOK", "CAME", "LEFT", "HELP", "MOVE",
            "REAL", "SAME", "TURN", "NEED", "FEEL", "THINK", "STILL",
            "ABOUT", "AFTER", "AGAIN", "BELOW", "COULD", "EVERY",
            "FIRST", "GREAT", "HEARD", "MIGHT", "NEVER", "OTHER",
            "PLACE", "POINT", "RIGHT", "SHALL", "SINCE", "START",
            "THEIR", "THERE", "THESE", "THING", "THOSE", "THREE",
            "TIMES", "TRIED", "UNDER", "UNTIL", "WHERE", "WHILE",
            "WORLD", "WOULD", "WRITE", "WRONG", "YOURS",
            # Financial words (not tickers)
            "RISK", "STOCK", "PRICE", "MARKET", "SHARE", "TRADE",
            "SELL", "RATE", "FUND", "BOND", "EARN", "LOSS", "GAIN",
            "BEAR", "BULL", "CALL", "PUTS", "SAFE", "DEBT", "CASH",
            "COMPARE", "ANALYZE", "ANALYSIS", "INVEST", "RETURN", "TODAY",
            "WORTH", "VALUE", "CHART", "TREND", "WATCH", "SPLIT",
            "RALLY", "CRASH", "SURGE", "RISE", "FALL", "DROP", "GROW",
            "MONEY", "HEDGE", "SHORT", "YIELD", "ALERT", "CLOSE",
            "OPEN", "BUY", "WHY",
        }

        # Structural heuristic: if a candidate appears as lowercase in the
        # original message, it's almost certainly an English word, not a ticker.
        # Real tickers are written in uppercase by users (AAPL, GOOGL, TCS.NS).
        original_words = set(re.findall(r'\b[a-z]{2,}\b', message))

        for sym in candidates:
            if sym in stop_words:
                continue
            if len(sym) < 2:
                continue
            # If the word appears in lowercase in the original message,
            # treat it as a regular word, not a ticker symbol
            if sym.lower() in original_words:
                continue
            symbols.append(sym)

        return symbols[:3]  # Max 3 symbols per query

    async def _fetch_market_data(self, symbol: str) -> str:
        """Fetch real market data for injection into the LLM context. Returns empty string if unavailable."""
        has_data = False
        parts = [f"\n[MARKET DATA for {symbol}]"]

        # Quote
        try:
            quote_result = await self._data.get_quote(symbol)
            quote = quote_result.data if quote_result.available else None
            if quote:
                has_data = True
                quote.pop("_validation", None)
                parts.append(
                    f"Price: {quote.get('price', 'N/A')} | "
                    f"Change: {quote.get('change', 0)} ({quote.get('change_percent', 0):.2f}%) | "
                    f"Volume: {quote.get('volume', 'N/A')} | "
                    f"High: {quote.get('high', 'N/A')} | Low: {quote.get('low', 'N/A')} | "
                    f"Market Cap: {self._fmt_market_cap(quote.get('market_cap'))} | "
                    f"P/E: {quote.get('pe_ratio', 'N/A')}"
                )
        except Exception:
            pass

        # Company info (lightweight)
        try:
            info_result = await self._data.get_company_info(symbol)
            info = info_result.data if info_result.available else None
            if info:
                has_data = True
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
                        f"D/E: {self._fmt_de_ratio(metrics.get('debt_to_equity'))}"
                    )
        except Exception:
            pass

        if not has_data:
            return ""

        parts.append("[END MARKET DATA]\n")
        return "\n".join(parts)

    @staticmethod
    def _fmt_market_cap(val) -> str:
        """Format market cap as human-readable string."""
        if val is None:
            return "N/A"
        try:
            v = float(val)
            if v >= 1e12:
                return f"{v / 1e12:.2f}T"
            if v >= 1e9:
                return f"{v / 1e9:.2f}B"
            if v >= 1e6:
                return f"{v / 1e6:.2f}M"
            return f"{v:,.0f}"
        except (TypeError, ValueError):
            return str(val)

    @staticmethod
    def _fmt_de_ratio(val) -> str:
        """Normalize D/E ratio (some providers return %-based, e.g. 22.85 = 0.23)."""
        if val is None:
            return "N/A"
        try:
            v = float(val)
            # Some providers return debtToEquity as percentage-based
            if v > 5:  # Likely percentage format
                v = v / 100.0
            return f"{v:.2f}"
        except (TypeError, ValueError):
            return str(val)

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
            data_str = await self._fetch_market_data(sym)
            if data_str:
                session.add_entity(sym)
                data_context += data_str
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

        config = LLMConfig(max_tokens=3072, temperature=0.4)

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
            data_str = await self._fetch_market_data(sym)
            if data_str:
                session.add_entity(sym)
                data_context += data_str
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

        config = LLMConfig(max_tokens=3072, temperature=0.4)

        full_response = ""
        async for token in self._llm.stream(llm_messages, config):
            full_response += token
            yield token

        session.add_message("assistant", full_response)

"""
Document ingestion pipeline for RAG research.

Gathers documents from Yahoo Finance and structures them for embedding:
1. Company description and business summary
2. Financial metrics as structured text
3. News articles (titles + summaries)
4. Sector / industry context
5. Key financial ratios narrative

Text is chunked with overlap before insertion into the vector store.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Dict, List

import yfinance as yf

from app.core.logging import get_logger
from app.engines.rag.vector_store import vector_store

logger = get_logger(__name__)

_executor = ThreadPoolExecutor(max_workers=2)


class DocumentProcessor:
    """Fetches, chunks, and indexes company documents for RAG retrieval."""

    def __init__(self) -> None:
        self._vector_store = vector_store

    # ── Public API ──────────────────────────────────────────────

    async def index_company(self, symbol: str) -> Dict[str, Any]:
        """Index all available documents for *symbol*.

        Returns:
            ``{"symbol", "documents_indexed", "sources": [...]}}``
        """
        loop = asyncio.get_running_loop()
        ticker = yf.Ticker(symbol)

        # Fetch data in parallel via thread pool (yfinance is sync)
        info_future = loop.run_in_executor(_executor, lambda: ticker.info)
        news_future = loop.run_in_executor(_executor, lambda: getattr(ticker, "news", []))

        info = await info_future
        news = await news_future

        if not info:
            logger.warning("index_company_no_info", symbol=symbol)
            return {"symbol": symbol, "documents_indexed": 0, "sources": []}

        # Delete old collection so we rebuild from scratch
        self._vector_store.delete_collection(symbol)

        # Build document batches
        all_docs: List[Dict[str, Any]] = []
        all_docs.extend(self._create_company_docs(symbol, info))
        all_docs.extend(self._create_financial_docs(symbol, info))
        all_docs.extend(self._create_news_docs(symbol, news or []))
        all_docs.extend(self._create_sector_docs(symbol, info))

        # Index into vector store
        count = self._vector_store.add_documents(symbol, all_docs)
        sources = self._vector_store.list_sources(symbol)

        logger.info(
            "company_indexed",
            symbol=symbol,
            documents=count,
            sources=len(sources),
        )

        return {
            "symbol": symbol.upper(),
            "documents_indexed": count,
            "sources": sources,
        }

    # ── Document creation helpers ───────────────────────────────

    def _create_company_docs(
        self, symbol: str, info: dict
    ) -> List[Dict[str, Any]]:
        """Create documents from company description and overview."""
        docs: List[Dict[str, Any]] = []
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # Business summary (usually 2-3 paragraphs)
        summary = info.get("longBusinessSummary", "")
        if summary:
            chunks = self._chunk_text(summary, chunk_size=500, overlap=50)
            for i, chunk in enumerate(chunks):
                docs.append({
                    "id": f"{symbol}_company_desc_{i}",
                    "text": chunk,
                    "metadata": {
                        "source": "Yahoo Finance",
                        "type": "company_description",
                        "date": today,
                        "title": f"{info.get('shortName', symbol)} — Company Overview",
                    },
                })

        # Company overview card
        name = info.get("shortName", info.get("longName", symbol))
        sector = info.get("sector", "N/A")
        industry = info.get("industry", "N/A")
        employees = info.get("fullTimeEmployees", "N/A")
        website = info.get("website", "N/A")

        overview_text = (
            f"{name} operates in the {sector} sector, specifically in the "
            f"{industry} industry. The company has approximately {employees} "
            f"full-time employees. Website: {website}."
        )
        docs.append({
            "id": f"{symbol}_company_overview",
            "text": overview_text,
            "metadata": {
                "source": "Yahoo Finance",
                "type": "company_overview",
                "date": today,
                "title": f"{name} — Overview",
            },
        })

        return docs

    def _create_financial_docs(
        self, symbol: str, info: dict
    ) -> List[Dict[str, Any]]:
        """Create structured text from financial metrics."""
        docs: List[Dict[str, Any]] = []
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        name = info.get("shortName", symbol)

        # Key financial metrics as narrative text
        metrics_parts: List[str] = []

        market_cap = info.get("marketCap")
        if market_cap:
            metrics_parts.append(
                f"Market capitalisation: {self._fmt_large_num(market_cap)}"
            )

        for label, key in [
            ("Trailing P/E ratio", "trailingPE"),
            ("Forward P/E ratio", "forwardPE"),
            ("Earnings per share (EPS)", "trailingEps"),
            ("Revenue", "totalRevenue"),
            ("Revenue growth", "revenueGrowth"),
            ("Profit margin", "profitMargins"),
            ("Operating margin", "operatingMargins"),
            ("Return on equity (ROE)", "returnOnEquity"),
            ("Return on assets (ROA)", "returnOnAssets"),
            ("Debt-to-equity", "debtToEquity"),
            ("Current ratio", "currentRatio"),
            ("Dividend yield", "dividendYield"),
            ("Book value", "bookValue"),
            ("Free cash flow", "freeCashflow"),
        ]:
            val = info.get(key)
            if val is not None:
                if "margin" in key.lower() or "growth" in key.lower() or "yield" in key.lower() or "return" in key.lower():
                    metrics_parts.append(f"{label}: {val * 100:.1f}%")
                elif key in ("totalRevenue", "freeCashflow"):
                    metrics_parts.append(
                        f"{label}: {self._fmt_large_num(val)}"
                    )
                else:
                    metrics_parts.append(f"{label}: {val:.2f}")

        if metrics_parts:
            metrics_text = (
                f"Key financial metrics for {name} as of {today}:\n"
                + "\n".join(f"- {m}" for m in metrics_parts)
            )
            docs.append({
                "id": f"{symbol}_financial_metrics",
                "text": metrics_text,
                "metadata": {
                    "source": "Yahoo Finance",
                    "type": "financial_metrics",
                    "date": today,
                    "title": f"{name} — Financial Metrics",
                },
            })

        # Valuation narrative
        pe = info.get("trailingPE")
        fpe = info.get("forwardPE")
        pb = info.get("priceToBook")
        if pe or fpe or pb:
            val_parts = []
            if pe:
                val_parts.append(f"trailing P/E of {pe:.1f}")
            if fpe:
                val_parts.append(f"forward P/E of {fpe:.1f}")
            if pb:
                val_parts.append(f"price-to-book of {pb:.2f}")
            val_text = (
                f"{name} is currently valued at a {', '.join(val_parts)}. "
                f"This should be compared to sector peers for context."
            )
            docs.append({
                "id": f"{symbol}_valuation",
                "text": val_text,
                "metadata": {
                    "source": "Yahoo Finance",
                    "type": "valuation",
                    "date": today,
                    "title": f"{name} — Valuation",
                },
            })

        return docs

    def _create_news_docs(
        self, symbol: str, news: list
    ) -> List[Dict[str, Any]]:
        """Create documents from news articles."""
        docs: List[Dict[str, Any]] = []

        for i, article in enumerate(news[:15]):  # Cap at 15 articles
            title = article.get("title", "")
            publisher = article.get("publisher", "Unknown")
            link = article.get("link", "")

            # yfinance news timestamp is Unix epoch
            pub_time = article.get("providerPublishTime", 0)
            try:
                date_str = datetime.fromtimestamp(
                    pub_time, tz=timezone.utc
                ).strftime("%Y-%m-%d")
            except Exception:
                date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

            # Some articles have a 'summary' or 'description' field
            summary = article.get("summary", article.get("description", ""))

            text = f"News: {title}"
            if summary:
                text += f"\n{summary}"
            text += f"\nPublished by {publisher} on {date_str}."

            if not title:
                continue

            docs.append({
                "id": f"{symbol}_news_{i}",
                "text": text,
                "metadata": {
                    "source": publisher,
                    "type": "news",
                    "date": date_str,
                    "title": title,
                    "url": link,
                },
            })

        return docs

    def _create_sector_docs(
        self, symbol: str, info: dict
    ) -> List[Dict[str, Any]]:
        """Create sector/industry context documents."""
        docs: List[Dict[str, Any]] = []
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        name = info.get("shortName", symbol)
        sector = info.get("sector")
        industry = info.get("industry")

        if sector and industry:
            text = (
                f"{name} belongs to the {sector} sector and the {industry} "
                f"industry. When evaluating this company, comparisons should "
                f"be made against peers in the same sector. Sector-specific "
                f"factors like regulatory environment, cyclicality, and "
                f"competitive dynamics should be considered."
            )
            docs.append({
                "id": f"{symbol}_sector_context",
                "text": text,
                "metadata": {
                    "source": "Yahoo Finance",
                    "type": "sector_context",
                    "date": today,
                    "title": f"{name} — Sector Context ({sector})",
                },
            })

        return docs

    # ── Text utilities ──────────────────────────────────────────

    def _chunk_text(
        self, text: str, chunk_size: int = 500, overlap: int = 50
    ) -> List[str]:
        """Split *text* into overlapping word-based chunks."""
        words = text.split()
        if len(words) <= chunk_size:
            return [text]

        chunks: List[str] = []
        start = 0
        while start < len(words):
            end = start + chunk_size
            chunk = " ".join(words[start:end])
            chunks.append(chunk)
            start = end - overlap

        return chunks

    @staticmethod
    def _fmt_large_num(val: float | int | None) -> str:
        if val is None:
            return "N/A"
        val = float(val)
        if val >= 1e12:
            return f"₹{val / 1e12:.2f}T"
        if val >= 1e9:
            return f"₹{val / 1e9:.2f}B"
        if val >= 1e7:
            return f"₹{val / 1e7:.2f}Cr"
        if val >= 1e5:
            return f"₹{val / 1e5:.2f}L"
        return f"₹{val:,.0f}"

"""
RAG Retriever — semantic retrieval with citation extraction.

Given a query (e.g. "revenue growth outlook for RELIANCE"), this module:
1. Searches the ChromaDB vector store for relevant chunks
2. Formats them with [SOURCE N] markers
3. Builds a source reference list for the frontend

The formatted context is then injected into the LLM prompt so the
research engine can produce cited reports.
"""

from __future__ import annotations

from typing import Any, Dict, List

from app.core.logging import get_logger
from app.engines.rag.vector_store import vector_store

logger = get_logger(__name__)


class RAGRetriever:
    """Retrieve, rank, and format context for LLM prompting."""

    def __init__(self) -> None:
        self._vector_store = vector_store

    def retrieve_context(
        self,
        symbol: str,
        query: str,
        max_chunks: int = 8,
        max_chars: int = 6000,
    ) -> Dict[str, Any]:
        """Retrieve relevant context for a research query.

        Returns::

            {
                "context_text": str,      # text with [SOURCE N] markers
                "sources": [              # ordered source list
                    {"id": 1, "title": str, "source": str,
                     "date": str, "type": str, "url": str},
                    ...
                ],
                "chunks_retrieved": int,
                "has_context": bool,
            }
        """
        if not self._vector_store.has_documents(symbol):
            return {
                "context_text": "",
                "sources": [],
                "chunks_retrieved": 0,
                "has_context": False,
            }

        # Run semantic search
        results = self._vector_store.search(
            symbol=symbol,
            query=query,
            n_results=max_chunks,
        )

        if not results:
            return {
                "context_text": "",
                "sources": [],
                "chunks_retrieved": 0,
                "has_context": False,
            }

        # De-duplicate by source title (keep highest relevance)
        seen_titles: Dict[str, int] = {}
        unique_results: List[Dict[str, Any]] = []
        for r in results:
            title = r.get("metadata", {}).get("title", "")
            if title in seen_titles:
                continue
            seen_titles[title] = len(unique_results)
            unique_results.append(r)

        # Build formatted context with [SOURCE N] markers
        context_parts: List[str] = []
        sources: List[Dict[str, Any]] = []
        total_chars = 0

        for i, result in enumerate(unique_results):
            text = result.get("text", "")
            meta = result.get("metadata", {})
            source_id = i + 1

            # Truncate if we'd exceed max_chars
            if total_chars + len(text) > max_chars:
                remaining = max_chars - total_chars
                if remaining > 100:
                    text = text[:remaining] + "…"
                else:
                    break

            context_parts.append(
                f"[SOURCE {source_id}] ({meta.get('title', 'Untitled')} — "
                f"{meta.get('source', 'Unknown')}, {meta.get('date', 'N/A')}):\n"
                f"{text}"
            )

            sources.append({
                "id": source_id,
                "title": meta.get("title", "Untitled"),
                "source": meta.get("source", "Unknown"),
                "date": meta.get("date", ""),
                "type": meta.get("type", "unknown"),
                "url": meta.get("url", ""),
                "relevance": result.get("relevance", 0.0),
            })

            total_chars += len(text)

        context_text = "\n\n".join(context_parts)

        logger.info(
            "rag_context_retrieved",
            symbol=symbol,
            chunks=len(sources),
            chars=total_chars,
        )

        return {
            "context_text": context_text,
            "sources": sources,
            "chunks_retrieved": len(sources),
            "has_context": True,
        }

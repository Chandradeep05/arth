"""
ChromaDB vector store wrapper for RAG research.

Runs in-memory mode (Render has ephemeral filesystem — index is rebuilt
on demand per stock).  Uses ChromaDB's default ONNX embedding function
(all-MiniLM-L6-v2, ~80 MB download, NO torch dependency).

Usage:
    from app.engines.rag.vector_store import vector_store

    vector_store.add_documents("RELIANCE.NS", docs)
    results = vector_store.search("RELIANCE.NS", "quarterly revenue growth")
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import chromadb

from app.core.logging import get_logger

logger = get_logger(__name__)


class VectorStore:
    """Lightweight ChromaDB wrapper with per-symbol collections."""

    def __init__(self) -> None:
        # Ephemeral in-memory client — no disk persistence
        self._client = chromadb.Client()
        logger.info("vector_store_initialized", mode="in-memory")

    # ── Collection helpers ──────────────────────────────────────

    def _collection_name(self, symbol: str) -> str:
        """Sanitise a ticker symbol into a valid ChromaDB collection name."""
        # ChromaDB requires: 3-63 chars, starts/ends with alphanum, [a-z0-9_-]
        name = f"arth_{symbol.replace('.', '_').replace('^', 'idx_').lower()}"
        # Clamp length
        return name[:63]

    def get_or_create_collection(self, symbol: str) -> chromadb.Collection:
        """Get (or create) the collection for *symbol*."""
        name = self._collection_name(symbol)
        return self._client.get_or_create_collection(name=name)

    # ── Write ───────────────────────────────────────────────────

    def add_documents(
        self,
        symbol: str,
        documents: List[Dict[str, Any]],
    ) -> int:
        """Add documents to the vector store.

        Each element of *documents* must contain:
            id   — unique string (e.g. ``"RELIANCE.NS_news_0"``)
            text — the textual content to embed
            metadata — dict with at least ``source``, ``type``, ``date``

        Returns:
            Number of documents added.
        """
        if not documents:
            return 0

        collection = self.get_or_create_collection(symbol)

        ids: List[str] = []
        texts: List[str] = []
        metadatas: List[Dict[str, str]] = []

        for doc in documents:
            doc_id = doc.get("id", "")
            text = doc.get("text", "")
            if not doc_id or not text:
                continue
            ids.append(doc_id)
            texts.append(text)
            # ChromaDB metadata values must be str/int/float/bool
            raw_meta = doc.get("metadata", {})
            metadatas.append({k: str(v) for k, v in raw_meta.items()})

        if not ids:
            return 0

        try:
            collection.upsert(ids=ids, documents=texts, metadatas=metadatas)
            logger.info(
                "documents_indexed",
                symbol=symbol,
                count=len(ids),
                collection=collection.name,
            )
            return len(ids)
        except Exception as e:
            logger.error("document_indexing_failed", symbol=symbol, error=str(e))
            return 0

    # ── Read / Search ───────────────────────────────────────────

    def search(
        self,
        symbol: str,
        query: str,
        n_results: int = 5,
    ) -> List[Dict[str, Any]]:
        """Semantic search over indexed documents.

        Returns a list of dicts::

            {"text": str, "metadata": dict, "relevance": float}

        Ordered by descending relevance.
        """
        if not self.has_documents(symbol):
            return []

        collection = self.get_or_create_collection(symbol)
        try:
            results = collection.query(query_texts=[query], n_results=n_results)
        except Exception as e:
            logger.error("vector_search_failed", symbol=symbol, error=str(e))
            return []

        output: List[Dict[str, Any]] = []
        if results and results["documents"]:
            docs = results["documents"][0]
            metas = results["metadatas"][0] if results["metadatas"] else [{}] * len(docs)
            dists = results["distances"][0] if results["distances"] else [0.0] * len(docs)

            for text, meta, dist in zip(docs, metas, dists):
                # ChromaDB returns L2 distance — convert to a 0-1 relevance
                relevance = max(0.0, 1.0 - dist / 2.0)
                output.append({
                    "text": text,
                    "metadata": meta,
                    "relevance": round(relevance, 4),
                })

        return output

    # ── Utilities ───────────────────────────────────────────────

    def has_documents(self, symbol: str) -> bool:
        """Check whether any documents are indexed for *symbol*."""
        return self.get_document_count(symbol) > 0

    def get_document_count(self, symbol: str) -> int:
        """Return the number of indexed documents for *symbol*."""
        try:
            collection = self.get_or_create_collection(symbol)
            return collection.count()
        except Exception:
            return 0

    def list_sources(self, symbol: str) -> List[Dict[str, str]]:
        """List unique sources indexed for *symbol*."""
        if not self.has_documents(symbol):
            return []

        collection = self.get_or_create_collection(symbol)
        try:
            all_docs = collection.get(include=["metadatas"])
            seen: Dict[str, Dict[str, str]] = {}
            for meta in (all_docs.get("metadatas") or []):
                source = meta.get("source", "Unknown")
                doc_type = meta.get("type", "unknown")
                key = f"{source}:{doc_type}"
                if key not in seen:
                    seen[key] = {
                        "source": source,
                        "type": doc_type,
                        "date": meta.get("date", ""),
                        "url": meta.get("url", ""),
                    }
            return list(seen.values())
        except Exception as e:
            logger.error("list_sources_failed", symbol=symbol, error=str(e))
            return []

    def delete_collection(self, symbol: str) -> None:
        """Delete all documents for *symbol* (re-index from scratch)."""
        name = self._collection_name(symbol)
        try:
            self._client.delete_collection(name)
            logger.info("collection_deleted", symbol=symbol)
        except Exception:
            pass  # Collection may not exist


# ── Module-level singleton ───────────────────────────────────
vector_store = VectorStore()

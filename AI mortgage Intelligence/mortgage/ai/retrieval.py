"""
mortgage/ai/retrieval.py
=========================
RAG retrieval module for the AI Mortgage Intelligence Agent.

Architecture
------------
1. On first call, the knowledge base (from knowledge.py) is embedded using
   sentence-transformers and stored in an in-memory ChromaDB collection.
2. At query time, the query is embedded and the top-k most relevant chunks
   are retrieved using cosine similarity.
3. The retrieved chunks are returned as a formatted string ready to be
   injected into the Claude system prompt.

Dependencies (must be installed):
    pip install chromadb>=0.5.0 sentence-transformers>=3.0.0
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Lazy imports — chromadb and sentence_transformers are large; only load when
# actually needed so the app starts fast even if they aren't installed.
# ─────────────────────────────────────────────────────────────────────────────

_collection = None          # ChromaDB collection (loaded once)
_embedder   = None          # SentenceTransformer model (loaded once)
_RAG_READY  = False         # Set to True after successful initialisation
_RAG_ERROR  = ""            # Human-readable error if initialisation failed

EMBEDDING_MODEL = "all-MiniLM-L6-v2"   # ~22 MB, fast, good for English semantic search
COLLECTION_NAME = "mortgage_knowledge"
TOP_K           = 4                     # number of chunks to retrieve per query


def _get_embedder():
    """Load (or return cached) SentenceTransformer model."""
    global _embedder
    if _embedder is None:
        from sentence_transformers import SentenceTransformer  # type: ignore
        logger.info("Loading sentence-transformer model: %s", EMBEDDING_MODEL)
        _embedder = SentenceTransformer(EMBEDDING_MODEL)
    return _embedder


def _get_collection():
    """
    Return (or build) the ChromaDB in-memory collection.

    On first call, embeds all KNOWLEDGE_CHUNKS and upserts them.
    Subsequent calls return the cached collection.
    """
    global _collection, _RAG_READY, _RAG_ERROR

    if _collection is not None:
        return _collection

    try:
        import chromadb  # type: ignore
        from mortgage.ai.knowledge import KNOWLEDGE_CHUNKS

        embedder = _get_embedder()

        # In-memory client — no persistence needed; fast startup
        client = chromadb.Client()

        # Use cosine similarity (better for semantic search than L2)
        _collection = client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )

        # Check if already populated (handles hot-reload in Streamlit)
        existing = _collection.count()
        if existing < len(KNOWLEDGE_CHUNKS):
            ids        = [chunk["id"] for chunk in KNOWLEDGE_CHUNKS]
            documents  = [chunk["content"] for chunk in KNOWLEDGE_CHUNKS]
            metadatas  = [
                {"category": chunk["category"], "title": chunk["title"]}
                for chunk in KNOWLEDGE_CHUNKS
            ]

            logger.info("Embedding %d knowledge chunks...", len(KNOWLEDGE_CHUNKS))
            embeddings = embedder.encode(documents, show_progress_bar=False).tolist()

            _collection.upsert(
                ids=ids,
                documents=documents,
                metadatas=metadatas,
                embeddings=embeddings,
            )
            logger.info("Knowledge base loaded into ChromaDB (%d chunks).", len(KNOWLEDGE_CHUNKS))

        _RAG_READY = True
        return _collection

    except ImportError as e:
        _RAG_ERROR = (
            f"RAG not available — missing dependency: {e}. "
            f"Run: pip install chromadb sentence-transformers"
        )
        logger.warning(_RAG_ERROR)
        return None
    except Exception as e:
        _RAG_ERROR = f"RAG initialisation failed: {e}"
        logger.exception(_RAG_ERROR)
        return None


def is_ready() -> tuple[bool, str]:
    """
    Return (True, "") if the RAG system is operational, or (False, error_msg).

    Calling this triggers initialisation if it hasn't happened yet.
    Safe to call from Streamlit at startup.
    """
    _get_collection()
    return _RAG_READY, _RAG_ERROR


def retrieve(query: str, top_k: int = TOP_K) -> str:
    """
    Retrieve the most relevant Canadian mortgage knowledge chunks for `query`.

    Returns a formatted multi-line string ready to inject into a Claude
    system prompt.  If RAG is unavailable, returns an empty string (the
    caller should degrade gracefully — Claude still answers without RAG context).

    Args:
        query  : The user's question or the most recent message.
        top_k  : Number of chunks to include (default 4).

    Returns:
        A string like:
            === Relevant Canadian Mortgage Knowledge ===

            [Semi-Annual Compounding (Interest Calculation)]
            Under the Canadian Interest Act, ...

            [Prepayment Penalty (Prepayment)]
            For fixed-rate mortgages ...
    """
    collection = _get_collection()
    if collection is None:
        return ""

    try:
        embedder   = _get_embedder()
        query_emb  = embedder.encode([query], show_progress_bar=False).tolist()

        results = collection.query(
            query_embeddings=query_emb,
            n_results=min(top_k, collection.count()),
            include=["documents", "metadatas", "distances"],
        )

        chunks     = results["documents"][0]
        metadatas  = results["metadatas"][0]
        distances  = results["distances"][0]

        if not chunks:
            return ""

        lines = ["=== Relevant Canadian Mortgage Knowledge ===\n"]
        for doc, meta, dist in zip(chunks, metadatas, distances):
            # Cosine distance → similarity = 1 - distance
            similarity = 1 - dist
            if similarity < 0.15:
                # Very low relevance — skip to avoid noise
                continue
            title    = meta.get("title", "")
            category = meta.get("category", "")
            lines.append(f"[{title} ({category})]")
            lines.append(doc)
            lines.append("")   # blank line between chunks

        if len(lines) == 1:
            return ""   # nothing passed the similarity threshold

        return "\n".join(lines)

    except Exception as e:
        logger.warning("RAG retrieval failed: %s", e)
        return ""


def retrieve_chunks_metadata(query: str, top_k: int = TOP_K) -> list[dict]:
    """
    Same as retrieve() but returns structured metadata dicts instead of a string.
    Useful for displaying source citations in the UI.

    Returns a list of dicts: [{title, category, content, similarity}, ...]
    """
    collection = _get_collection()
    if collection is None:
        return []

    try:
        embedder  = _get_embedder()
        query_emb = embedder.encode([query], show_progress_bar=False).tolist()

        results = collection.query(
            query_embeddings=query_emb,
            n_results=min(top_k, collection.count()),
            include=["documents", "metadatas", "distances"],
        )

        output = []
        for doc, meta, dist in zip(
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0],
        ):
            similarity = 1 - dist
            if similarity < 0.15:
                continue
            output.append({
                "title":      meta.get("title", ""),
                "category":   meta.get("category", ""),
                "content":    doc,
                "similarity": round(similarity, 3),
            })
        return output

    except Exception as e:
        logger.warning("RAG metadata retrieval failed: %s", e)
        return []

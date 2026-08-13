"""
Embedding Service — BGE-M3 (Dense) + BM25 (Sparse)
====================================================
Best Practices Applied (2026):
- Models are NOT loaded at import time. They are initialized lazily via initialize().
- The lifespan in session.py will call initialize() once at startup.
- asyncio.to_thread → keeps the FastAPI event loop non-blocking.
"""

import asyncio
import structlog
from fastembed import SparseTextEmbedding
from sentence_transformers import SentenceTransformer

logger = structlog.get_logger()


class EmbeddingService:
    """
    Manages BGE-M3 (Dense via sentence-transformers) and BM25 (Sparse via fastembed) embedding models.

    Lifecycle:
        - Call await embedding_service.initialize() once inside the FastAPI lifespan.
        - Models are then held in memory as singletons for the app lifetime.
    """

    def __init__(self):
        self._dense_model: SentenceTransformer | None = None
        self._sparse_model: SparseTextEmbedding | None = None

    async def initialize(self) -> None:
        """
        Load both models into memory once at startup.
        Runs in a thread to avoid blocking the event loop during the heavy
        model download / initialization.
        """

        def _load_models():
            dense = SentenceTransformer(
                "BAAI/bge-m3",
                device="cpu"
            )
            sparse = SparseTextEmbedding(
                model_name="Qdrant/bm25",
                cache_dir="./.model_cache",
            )
            return dense, sparse

        self._dense_model, self._sparse_model = await asyncio.to_thread(_load_models)
        logger.info(
            "Embedding models loaded ✅",
            dense="BAAI/bge-m3 (via sentence-transformers)",
            sparse="Qdrant/bm25",
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_dense_embedding(self, text: str) -> list[float]:
        """
        Returns a 1024-dim dense vector via BGE-M3.
        Runs in a thread pool to keep the async event loop free.
        """
        assert self._dense_model is not None, "EmbeddingService not initialized"

        def _embed() -> list[float]:
            embeddings = self._dense_model.encode(
                [text],
                normalize_embeddings=True,
                show_progress_bar=False
            )
            return embeddings[0].tolist()

        return await asyncio.to_thread(_embed)

    async def get_sparse_embedding(self, text: str):
        """
        Returns a BM25 SparseEmbedding (indices + values).
        Runs in a thread pool to keep the async event loop free.
        """
        assert self._sparse_model is not None, "EmbeddingService not initialized"

        def _embed():
            return list(self._sparse_model.embed([text]))[0]  # type: ignore[union-attr]

        return await asyncio.to_thread(_embed)

    async def get_both_embeddings(self, text: str) -> tuple[list[float], object]:
        """
        Fetches Dense + Sparse vectors concurrently via asyncio.gather.
        Used by both the indexing pipeline and the hybrid search query path.
        """
        dense, sparse = await asyncio.gather(
            self.get_dense_embedding(text),
            self.get_sparse_embedding(text),
        )
        return dense, sparse


# Module-level instance — NOT loaded yet, initialize() called from lifespan
embedding_service = EmbeddingService()

"""
Reranker Service — BAAI/bge-reranker-v2-m3 (Cross-Encoder)
===========================================================
Best Practices Applied (2026):
- Correct import path: fastembed.rerank.cross_encoder (NOT top-level fastembed)
- Lazy initialization via initialize() called from the FastAPI lifespan — NOT at import time.
- asyncio.to_thread → reranking is CPU-bound; running it in the event loop would freeze the server.
- Scores returned by .rerank() are raw floats (can be negative); sorted descending = most relevant first.
- Input:  Top-30 candidates from RRF (payloads from Qdrant)
- Output: Top-N (default 4) for the LLM context window
"""

import asyncio
import structlog
from fastembed.rerank.cross_encoder import TextCrossEncoder  # ✅ صح (ليس from fastembed import)

logger = structlog.get_logger()


class RerankerService:
    """
    Cross-Encoder Reranker using bge-reranker-v2-m3.
    Reads query + each passage jointly (word-by-word) to produce a precise
    relevance score — unlike RRF which only fuses rank positions.

    Lifecycle:
        - Call await reranker_service.initialize() once inside the FastAPI lifespan.
        - Model is then held in memory as a singleton for the app lifetime.
    """

    def __init__(self):
        # ✅ لا نحمّل النموذج هنا — فقط نحجز المكان
        self._model: TextCrossEncoder | None = None

    async def initialize(self) -> None:
        """
        Load the reranker model once at startup inside a background thread.
        Avoids blocking the FastAPI event loop during the heavy ONNX init.
        """

        def _load():
            return TextCrossEncoder(
                model_name="BAAI/bge-reranker-v2-m3",
                cache_dir="./.model_cache",
            )

        self._model = await asyncio.to_thread(_load)
        logger.info("Reranker model loaded ✅", model="BAAI/bge-reranker-v2-m3")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def rerank(
        self,
        query: str,
        passages: list[dict],
        top_n: int = 4,
        text_field: str = "raw_text",
    ) -> list[dict]:
        """
        Re-scores each passage against the query jointly (Cross-Encoder).
        Returns the top_n most relevant passages sorted by score descending.

        Args:
            query:      The student's question.
            passages:   List of Qdrant payload dicts (from RRF top-30).
            top_n:      How many passages to return for the LLM context (default 4).
            text_field: The key inside each payload dict that holds the passage text.

        Returns:
            Sorted list of top_n payload dicts, most relevant first.
        """
        assert self._model is not None, "RerankerService not initialized"

        if not passages:
            return []

        # استخراج النصوص من الـ payloads لإرسالها للـ Reranker
        texts = [p.get(text_field, "") for p in passages]

        def _rerank() -> list[dict]:
            # .rerank() يُرجع generator من float scores (يمكن أن تكون سلبية)
            # الأعلى score = الأكثر صلة بالسؤال
            scores: list[float] = list(self._model.rerank(query, texts))  # type: ignore[union-attr]

            # دمج كل score مع الـ payload الأصلي ثم الترتيب من الأعلى للأدنى
            scored_pairs = sorted(
                zip(scores, passages),
                key=lambda pair: pair[0],
                reverse=True,
            )

            return [payload for _, payload in scored_pairs[:top_n]]

        return await asyncio.to_thread(_rerank)


# Module-level instance — NOT loaded yet, initialize() called from lifespan
reranker_service = RerankerService()

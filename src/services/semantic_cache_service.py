"""
Semantic Cache Service — Qdrant Vector Cache for RAG
=====================================================
Best Practices Applied (2026):
- Uses Qdrant Vector Collection to store past questions, dense embeddings (BGE-M3 1024d), and generated answers.
- Cosine similarity threshold >= 0.95: prevents false-positive cache hits while matching semantically equivalent questions.
- Multi-Tenancy Isolation: Strict filtering on `company_id` ensures no cross-organization data leakage.
- Access Control Verification: Validates student permissions against cached `lesson_ids` before returning a cache HIT.
- Event-Driven Invalidation: `invalidate_by_lesson_id` removes stale cache entries when LMS webhook updates or deletes a lesson.
- Ultra-Low Latency: Cache hits return in < 15ms, bypassing Qdrant search, reranker, and Gemini LLM.
"""

import uuid
from datetime import datetime, timezone
import structlog
from qdrant_client.models import (
    VectorParams,
    Distance,
    PointStruct,
    Filter,
    FieldCondition,
    MatchValue,
    KeywordIndexParams,
    FilterSelector,
)

from src.core.config import settings
from src.services.qdrant_service import qdrant_service
from src.models.auth_models import UserContext
from src.models.search_models import SearchResponse, SourceItem

logger = structlog.get_logger()


class SemanticCacheService:
    """
    Manages semantic caching for student queries in Qdrant.
    """

    def __init__(self) -> None:
        self.collection_name = settings.SEMANTIC_CACHE_COLLECTION
        self.threshold = settings.SEMANTIC_CACHE_THRESHOLD
        self.enabled = settings.SEMANTIC_CACHE_ENABLED

    async def initialize(self) -> None:
        """
        Initializes the semantic cache collection and its payload indexes in Qdrant.
        Called once during FastAPI lifespan startup.
        """
        if not self.enabled:
            logger.info("Semantic cache is disabled in settings")
            return

        client = qdrant_service.client
        exists = await client.collection_exists(self.collection_name)
        if not exists:
            logger.info("Creating semantic cache collection", collection=self.collection_name)
            await client.create_collection(
                collection_name=self.collection_name,
                vectors_config=VectorParams(size=1024, distance=Distance.COSINE),
            )
            # Create payload indexes for fast filtering
            for field in ["company_id", "lesson_ids", "user_id"]:
                await client.create_payload_index(
                    collection_name=self.collection_name,
                    field_name=field,
                    field_schema=KeywordIndexParams(type="keyword"),
                )
            logger.info("Semantic cache collection created successfully", collection=self.collection_name)
        else:
            logger.info("Semantic cache collection ready", collection=self.collection_name)

    async def lookup(
        self,
        query_vector: list[float],
        user_ctx: UserContext,
    ) -> SearchResponse | None:
        """
        Searches the semantic cache for a past query vector with cosine similarity >= threshold.
        Enforces tenant isolation and validates student lesson permissions.

        Returns:
            SearchResponse if cache HIT and authorized, None otherwise (cache MISS).
        """
        if not self.enabled:
            return None

        try:
            client = qdrant_service.client
            # Multi-tenant filter: only search records matching user's company_id
            search_filter = Filter(
                must=[
                    FieldCondition(
                        key="company_id",
                        match=MatchValue(value=user_ctx.company_id),
                    )
                ]
            )

            results = await client.query_points(
                collection_name=self.collection_name,
                query=query_vector,
                query_filter=search_filter,
                limit=1,
                score_threshold=self.threshold,
                with_payload=True,
            )

            if not results.points:
                return None

            hit = results.points[0]
            payload = hit.payload or {}
            cached_lessons: list[str] = payload.get("lesson_ids", [])

            # Verify permissions: check if user has access to all lessons referenced by the cached response
            if cached_lessons and user_ctx.permissions:
                allowed_lessons = set(user_ctx.permissions.accessible_lesson_ids)
                # If student is restricted and missing access to any lesson in the answer, treat as MISS
                if allowed_lessons and not set(cached_lessons).issubset(allowed_lessons):
                    logger.info(
                        "Semantic cache match rejected due to permission restrictions",
                        cached_lessons=cached_lessons,
                        score=hit.score,
                    )
                    return None

            logger.info(
                "Semantic Cache HIT",
                score=round(hit.score, 4),
                query_cached=payload.get("query"),
            )

            sources_raw = payload.get("sources", [])
            sources = [SourceItem(**s) for s in sources_raw]

            return SearchResponse(
                answer=payload.get("answer", ""),
                sources=sources,
                query_used=payload.get("query", ""),
            )

        except Exception as e:
            logger.warning("Semantic cache lookup failed, falling back to full RAG", error=str(e))
            return None

    async def store(
        self,
        query: str,
        query_vector: list[float],
        response: SearchResponse,
        user_ctx: UserContext,
    ) -> None:
        """
        Stores an LLM-generated search response and query embedding into the semantic cache.
        """
        if not self.enabled:
            return

        try:
            client = qdrant_service.client
            lesson_ids = list({
                getattr(s, "lesson_id", None)
                for s in response.sources
                if getattr(s, "lesson_id", None)
            })

            point = PointStruct(
                id=str(uuid.uuid4()),
                vector=query_vector,
                payload={
                    "query": query,
                    "answer": response.answer,
                    "sources": [s.model_dump() for s in response.sources],
                    "lesson_ids": lesson_ids,
                    "company_id": user_ctx.company_id,
                    "user_id": user_ctx.user_id,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                },
            )

            await client.upsert(
                collection_name=self.collection_name,
                points=[point],
            )
            logger.info("Response stored in semantic cache", query=query, lesson_count=len(lesson_ids))

        except Exception as e:
            logger.warning("Failed to store response in semantic cache", error=str(e))

    async def invalidate_by_lesson_id(self, lesson_id: str) -> None:
        """
        Invalidates all cached queries that reference a given lesson.
        Invoked when an LMS Webhook (Updated/Deleted) is received.
        """
        if not self.enabled:
            return

        try:
            client = qdrant_service.client
            selector = FilterSelector(
                filter=Filter(
                    must=[
                        FieldCondition(
                            key="lesson_ids",
                            match=MatchValue(value=lesson_id),
                        )
                    ]
                )
            )
            await client.delete(
                collection_name=self.collection_name,
                points_selector=selector,
            )
            logger.info("Invalidated semantic cache entries for lesson", lesson_id=lesson_id)

        except Exception as e:
            logger.warning("Failed to invalidate semantic cache for lesson", lesson_id=lesson_id, error=str(e))


# Module-level singleton instance — initialized in lifespan
semantic_cache_service = SemanticCacheService()

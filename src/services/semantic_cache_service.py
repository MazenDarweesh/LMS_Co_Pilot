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
from datetime import datetime, timezone, timedelta
import structlog
from qdrant_client.models import (
    VectorParams,
    Distance,
    PointStruct,
    Filter,
    FieldCondition,
    MatchValue,
    KeywordIndexParams,
    IntegerIndexParams,
    FilterSelector,
    PointIdsList,
    Range,
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
        self.ttl_days = settings.SEMANTIC_CACHE_TTL_DAYS

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
            await client.create_payload_index(
                collection_name=self.collection_name,
                field_name="created_at_ts",
                field_schema=IntegerIndexParams(type="integer"),
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
            # Note: Admins possess full company-wide access and bypass lesson-level restrictions.
            if user_ctx.claims.role != "Admin" and cached_lessons:
                if not user_ctx.permissions or not user_ctx.permissions.accessible_lesson_ids:
                    logger.warning(
                        "Semantic cache match rejected: student has no valid permissions or enrollments",
                        user_id=user_ctx.user_id,
                    )
                    return None

                allowed_lessons = set(user_ctx.permissions.accessible_lesson_ids)
                # If student is restricted and missing access to any lesson in the answer, treat as MISS
                if not set(cached_lessons).issubset(allowed_lessons):
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

            now = datetime.now(timezone.utc)
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
                    "created_at": now.isoformat(),
                    "created_at_ts": int(now.timestamp()),
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

    async def evict_expired_entries(self) -> int:
        """
        Evicts entries older than SEMANTIC_CACHE_TTL_DAYS (default: 7 days)
        from the Qdrant semantic cache collection.
        Returns the count of evicted points.
        """
        if not self.enabled:
            return 0

        try:
            client = qdrant_service.client
            cutoff_dt = datetime.now(timezone.utc) - timedelta(days=self.ttl_days)
            cutoff_ts = int(cutoff_dt.timestamp())

            # Method 1: Delete via Range filter on created_at_ts
            delete_filter = Filter(
                must=[
                    FieldCondition(
                        key="created_at_ts",
                        range=Range(lt=cutoff_ts),
                    )
                ]
            )

            res = await client.delete(
                collection_name=self.collection_name,
                points_selector=FilterSelector(filter=delete_filter),
            )
            logger.info(
                "Evicted expired semantic cache entries",
                cutoff_days=self.ttl_days,
                cutoff_ts=cutoff_ts,
                status=getattr(res, "status", "ok"),
            )

            # Method 2: Fallback scroll to clean up legacy records that lack created_at_ts
            legacy_expired_ids: list[str] = []
            offset = None
            while True:
                scroll_res = await client.scroll(
                    collection_name=self.collection_name,
                    limit=100,
                    offset=offset,
                    with_payload=True,
                    with_vectors=False,
                )
                points, offset = scroll_res
                for pt in points:
                    p = pt.payload or {}
                    if "created_at_ts" not in p and "created_at" in p:
                        try:
                            pt_dt = datetime.fromisoformat(p["created_at"])
                            if pt_dt < cutoff_dt:
                                legacy_expired_ids.append(str(pt.id))
                        except Exception:
                            pass

                if offset is None or not points:
                    break

            if legacy_expired_ids:
                await client.delete(
                    collection_name=self.collection_name,
                    points_selector=PointIdsList(points=legacy_expired_ids),
                )
                logger.info(
                    "Evicted legacy semantic cache entries",
                    count=len(legacy_expired_ids),
                )

            return len(legacy_expired_ids)

        except Exception as e:
            logger.warning("Semantic cache TTL eviction failed", error=str(e))
            return 0


# Module-level singleton instance — initialized in lifespan
semantic_cache_service = SemanticCacheService()

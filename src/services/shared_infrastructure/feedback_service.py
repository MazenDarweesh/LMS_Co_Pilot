"""
Feedback Service — Storage and Quality Analytics Engine for Student Feedback
=============================================================================
Provides asynchronous, non-blocking persistence for student thumbs up/down ratings,
comments, and cited sources in PostgreSQL (search_feedback table).

Features:
- Idempotent UPSERT on (user_id, query_hash, answer_hash) to support vote amendments.
- Preserves raw query_text, answer_text, and comment for 100% RAG evaluation fidelity (ADR-15).
- Caps cited sources at 5 items to guard JSONB storage footprint.
- Tenant-isolated paginated retrieval and aggregate satisfaction analytics.
- Direct export formatting for offline Ragas automated test suites.
"""

import json
import structlog
import asyncpg
from typing import Any

logger = structlog.get_logger()


class FeedbackService:
    def __init__(self):
        self._pool: asyncpg.Pool | None = None

    def initialize(self, pool: asyncpg.Pool) -> None:
        """Initializes the service with the application's PostgreSQL connection pool."""
        self._pool = pool
        logger.info("Feedback Service ready ✅")

    async def save_feedback(
        self,
        tenant_id: str,
        user_id: str,
        user_role: str,
        query: str,
        answer: str,
        rating: str,
        query_hash: str,
        answer_hash: str,
        comment: str | None = None,
        lesson_id: str | None = None,
        thread_id: str | None = None,
        department_id: str | None = None,
        sources: list[dict[str, Any]] | None = None,
    ) -> None:
        """
        Asynchronously writes or updates a student feedback record in PostgreSQL.
        Runs as a non-blocking FastAPI BackgroundTask to ensure sub-15ms API response times.
        """
        if not self._pool:
            logger.warning("FeedbackService pool not initialized; skipping DB write")
            return

        # Cap sources to first 5 items to prevent unbounded JSONB storage growth
        bounded_sources = sources[:5] if sources else []

        query_sql = """
            INSERT INTO search_feedback (
                tenant_id, department_id, user_id, user_role,
                lesson_id, thread_id, query_hash, answer_hash,
                query_text, answer_text, rating, comment, sources
            ) VALUES (
                $1, $2, $3, $4,
                $5, $6, $7, $8,
                $9, $10, $11, $12, $13
            )
            ON CONFLICT (user_id, query_hash, answer_hash) DO UPDATE SET
                rating = EXCLUDED.rating,
                comment = EXCLUDED.comment,
                sources = EXCLUDED.sources,
                updated_at = NOW()
        """
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    query_sql,
                    tenant_id,
                    department_id,
                    user_id,
                    user_role,
                    lesson_id,
                    thread_id,
                    query_hash,
                    answer_hash,
                    query,
                    answer,
                    rating.upper(),
                    comment,
                    bounded_sources,
                )
            logger.info(
                "Student feedback saved to DB ✅",
                user_id=user_id,
                tenant_id=tenant_id,
                rating=rating.upper(),
                lesson_id=lesson_id,
                query_hash=query_hash,
            )
        except Exception as e:
            logger.error(
                "Failed to save student feedback to PostgreSQL",
                error=str(e),
                user_id=user_id,
                tenant_id=tenant_id,
                query_hash=query_hash,
            )

    async def get_tenant_feedback(
        self,
        tenant_id: str,
        lesson_id: str | None = None,
        rating: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """
        Retrieves paginated feedback records for a specific tenant with optional filters.
        """
        if not self._pool:
            return []

        conditions = ["tenant_id = $1"]
        params: list[Any] = [tenant_id]

        if lesson_id:
            params.append(lesson_id)
            conditions.append(f"lesson_id = ${len(params)}")

        if rating:
            params.append(rating.upper())
            conditions.append(f"rating = ${len(params)}")

        params.append(min(limit, 100))
        limit_idx = len(params)
        params.append(max(offset, 0))
        offset_idx = len(params)

        where_clause = " AND ".join(conditions)
        sql = f"""
            SELECT 
                id, tenant_id, department_id, user_id, user_role,
                lesson_id, thread_id, query_hash, answer_hash,
                query_text, answer_text, rating, comment, sources,
                created_at, updated_at
            FROM search_feedback
            WHERE {where_clause}
            ORDER BY created_at DESC
            LIMIT ${limit_idx} OFFSET ${offset_idx}
        """

        try:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(sql, *params)
                return [dict(r) for r in rows]
        except Exception as e:
            logger.error("Failed to query tenant feedback", error=str(e), tenant_id=tenant_id)
            return []

    async def get_feedback_analytics(
        self,
        tenant_id: str,
        lesson_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Calculates aggregate satisfaction metrics for a tenant or specific lesson.
        """
        if not self._pool:
            return {"total_votes": 0, "up_votes": 0, "down_votes": 0, "satisfaction_rate": 0.0}

        conditions = ["tenant_id = $1"]
        params: list[Any] = [tenant_id]

        if lesson_id:
            params.append(lesson_id)
            conditions.append("lesson_id = $2")

        where_clause = " AND ".join(conditions)
        sql = f"""
            SELECT 
                COUNT(*) AS total_votes,
                COUNT(*) FILTER (WHERE rating = 'UP') AS up_votes,
                COUNT(*) FILTER (WHERE rating = 'DOWN') AS down_votes
            FROM search_feedback
            WHERE {where_clause}
        """

        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(sql, *params)
                if not row:
                    return {"total_votes": 0, "up_votes": 0, "down_votes": 0, "satisfaction_rate": 0.0}

                total = row["total_votes"] or 0
                up = row["up_votes"] or 0
                down = row["down_votes"] or 0
                satisfaction = round((up / total) * 100, 2) if total > 0 else 0.0

                return {
                    "total_votes": total,
                    "up_votes": up,
                    "down_votes": down,
                    "satisfaction_rate": satisfaction,
                }
        except Exception as e:
            logger.error("Failed to calculate feedback analytics", error=str(e), tenant_id=tenant_id)
            return {"total_votes": 0, "up_votes": 0, "down_votes": 0, "satisfaction_rate": 0.0}

    async def export_for_ragas(
        self,
        tenant_id: str,
        lesson_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """
        Exports feedback records formatted directly for Ragas evaluation pipelines.
        Focuses on negative downvotes to diagnose hallucinations and retrieval misses.
        """
        records = await self.get_tenant_feedback(
            tenant_id=tenant_id,
            lesson_id=lesson_id,
            rating="DOWN",
            limit=limit,
        )

        ragas_dataset: list[dict[str, Any]] = []
        for r in records:
            raw_sources = r.get("sources") or []
            # Extract URLs or text markers for retrieved contexts
            contexts = []
            for s in raw_sources:
                if isinstance(s, dict):
                    url = s.get("url")
                    start = s.get("start")
                    contexts.append(f"{url}#t={start}s" if url and start is not None else str(url or ""))
                elif isinstance(s, str):
                    contexts.append(s)

            ragas_dataset.append({
                "user_input": r.get("query_text", ""),
                "response": r.get("answer_text", ""),
                "retrieved_contexts": contexts,
                "rating": r.get("rating", "DOWN"),
                "student_comment": r.get("comment"),
                "lesson_id": r.get("lesson_id"),
                "thread_id": r.get("thread_id"),
            })

        return ragas_dataset


# Module-level singleton
feedback_service = FeedbackService()

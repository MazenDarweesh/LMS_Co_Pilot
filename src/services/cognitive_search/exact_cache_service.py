"""
Exact In-Memory Cache Service — Fast Ingress Tier-1 Cache
=========================================================
Best Practices Applied (2026):
- Sub-2ms Exact Match In-Memory Cache using cachetools.TTLCache with LRU eviction.
- Key Generation: SHA256(company_id + ":" + department_id + ":" + role + ":" + normalized_query).
- Multi-Tenant & Department Isolation: Enforces tenant, department, and role boundaries directly within cache key.
- Permission Verification: Re-checks student lesson entitlements before returning cached SearchResponse.
- Thread-Safe: Uses threading.Lock to synchronize in-memory dictionary access under high concurrency.
- Invalidation Support: `invalidate_by_lesson_id` purges matching entries on LMS webhooks.
"""

import hashlib
import threading
import time
from typing import Any
import structlog
from cachetools import TTLCache

from src.core.config import settings
from src.core.metrics import record_cache_rbac_rejection
from src.models.auth_models import UserContext
from src.models.search_models import SearchResponse, SourceItem

logger = structlog.get_logger()


class CachedEntry:
    """Represents a cached search response with tenant and entitlement metadata."""
    __slots__ = ("response_dict", "lesson_ids", "company_id", "created_at")

    def __init__(
        self,
        response_dict: dict[str, Any],
        lesson_ids: list[str],
        company_id: str,
        created_at: float,
    ) -> None:
        self.response_dict = response_dict
        self.lesson_ids = lesson_ids
        self.company_id = company_id
        self.created_at = created_at


class ExactCacheService:
    """
    Tier-1 Exact In-Memory Cache.
    Intercepts repeated student questions in < 2ms, completely bypassing
    Dense/Sparse embedding generation, Qdrant HNSW vector search, and Gemini LLM calls.
    """

    def __init__(self) -> None:
        self._enabled = settings.EXACT_CACHE_ENABLED
        self._max_size = settings.EXACT_CACHE_MAX_SIZE
        self._ttl = settings.EXACT_CACHE_TTL_SECONDS
        self._cache: TTLCache | None = None
        self._lock = threading.Lock()

    def initialize(self) -> None:
        """Called from FastAPI lifespan during application startup."""
        if not self._enabled:
            logger.info("Exact In-Memory Cache is disabled in configuration")
            return

        with self._lock:
            self._cache = TTLCache(maxsize=self._max_size, ttl=self._ttl)
        logger.info(
            "Exact In-Memory Cache ready ✅",
            max_size=self._max_size,
            ttl_seconds=self._ttl,
        )

    def close(self) -> None:
        """Called on application shutdown."""
        with self._lock:
            if self._cache is not None:
                self._cache.clear()
        logger.info("Exact In-Memory Cache cleared and closed 🛑")

    def _compute_key(
        self,
        normalized_query: str,
        user_ctx: UserContext,
        scope_fingerprint: str = "",
    ) -> str:
        """Generates a deterministic 5D SHA256 key scoped strictly by tenant, department, role, and filter scope."""
        dept = user_ctx.claims.department_id or "global"
        role = user_ctx.claims.role
        raw_key = f"{user_ctx.company_id}:{dept}:{role}:{scope_fingerprint}:{normalized_query.strip().lower()}"
        return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()

    def lookup(
        self,
        normalized_query: str,
        user_ctx: UserContext,
        scope_fingerprint: str = "",
    ) -> SearchResponse | None:
        """
        Fast in-memory lookup (< 2ms).
        Returns SearchResponse if exact match exists and user is authorized to view referenced lessons.
        """
        if not self._enabled or self._cache is None:
            return None

        cache_key = self._compute_key(normalized_query, user_ctx, scope_fingerprint)

        with self._lock:
            entry: CachedEntry | None = self._cache.get(cache_key)

        if entry is None:
            return None

        # Multi-Tenant Guard: verify company isolation
        if entry.company_id != user_ctx.company_id:
            logger.warning(
                "Cross-tenant cache access blocked in ExactCache",
                expected=user_ctx.company_id,
                found=entry.company_id,
            )
            return None

        # Entitlement & RBAC Verification:
        # Admins have global access. For students, strictly verify all lesson_ids in the response are accessible.
        if user_ctx.claims.role != "Admin" and entry.lesson_ids:
            if not user_ctx.permissions or not user_ctx.permissions.accessible_lesson_ids:
                record_cache_rbac_rejection("exact")
                logger.warning(
                    "Exact cache match rejected: student has no valid permissions or enrollments",
                    user_id=user_ctx.user_id,
                )
                return None

            allowed = set(user_ctx.permissions.accessible_lesson_ids)
            if not set(entry.lesson_ids).issubset(allowed):
                record_cache_rbac_rejection("exact")
                logger.info(
                    "Exact cache match rejected due to student permission restrictions",
                    cached_lessons=entry.lesson_ids,
                    user_id=user_ctx.user_id,
                )
                return None

        # Reconstruct SearchResponse from cloned payload to prevent in-place mutation
        sources = [SourceItem(**s) for s in entry.response_dict.get("sources", [])]
        logger.info(
            "Exact In-Memory Cache HIT ⚡",
            key_hash=cache_key[:8],
            company_id=user_ctx.company_id,
        )
        return SearchResponse(
            answer=entry.response_dict.get("answer", ""),
            sources=sources,
            query_used=entry.response_dict.get("query_used", normalized_query),
        )

    def store(
        self,
        normalized_query: str,
        response: SearchResponse,
        user_ctx: UserContext,
        scope_fingerprint: str = "",
    ) -> None:
        """Stores a verified search response in the in-memory cache."""
        if not self._enabled or self._cache is None:
            return

        cache_key = self._compute_key(normalized_query, user_ctx, scope_fingerprint)
        lesson_ids = list({
            getattr(s, "lesson_id", None)
            for s in response.sources
            if getattr(s, "lesson_id", None)
        })

        # Save serializable dictionary to avoid mutable side effects
        response_dict = {
            "answer": response.answer,
            "sources": [s.model_dump() for s in response.sources],
            "query_used": response.query_used,
        }

        entry = CachedEntry(
            response_dict=response_dict,
            lesson_ids=lesson_ids,
            company_id=user_ctx.company_id,
            created_at=time.time(),
        )

        with self._lock:
            self._cache[cache_key] = entry

        logger.debug(
            "Stored response in ExactCache",
            key_hash=cache_key[:8],
            lessons=len(lesson_ids),
        )

    def invalidate_by_lesson_id(self, lesson_id: str) -> int:
        """
        Invalidates all in-memory entries referencing a given lesson_id.
        Triggered when an LMS update/delete webhook is received.
        """
        if self._cache is None:
            return 0

        evicted_keys: list[str] = []
        with self._lock:
            for key, entry in list(self._cache.items()):
                if lesson_id in entry.lesson_ids:
                    evicted_keys.append(key)
            for key in evicted_keys:
                self._cache.pop(key, None)

        if evicted_keys:
            logger.info("Invalidated exact cache entries for lesson", lesson_id=lesson_id, count=len(evicted_keys))
        return len(evicted_keys)

    def clear(self) -> None:
        """Purges all entries from exact cache."""
        with self._lock:
            if self._cache is not None:
                self._cache.clear()
        logger.info("Exact cache completely cleared")

    def get_stats(self) -> dict[str, Any]:
        """Returns diagnostic metrics about cache size and capacity."""
        with self._lock:
            if self._cache is None:
                return {"enabled": False, "size": 0, "max_size": self._max_size}
            return {
                "enabled": True,
                "size": len(self._cache),
                "max_size": self._cache.maxsize,
                "ttl_seconds": self._cache.ttl,
            }


# Module-level singleton instance
exact_cache_service = ExactCacheService()

import httpx
import structlog
from cachetools import TTLCache
from src.core.config import settings
from src.models.auth_models import UserPermissions, LessonFullContext

logger = structlog.get_logger()

class LMSClientService:
    """
    HTTP Client to securely communicate with the main .NET ERP Backend.
    Uses httpx.AsyncClient for high performance asynchronous requests.
    Includes a 5-minute TTLCache to prevent internal DoS on user permissions.
    """
    def __init__(self):
        self._client: httpx.AsyncClient | None = None
        self._perms_cache: TTLCache | None = None
        self._lesson_context_cache: TTLCache | None = None

    def initialize(self) -> None:
        """Called from FastAPI lifespan — never in __init__."""
        self._client = httpx.AsyncClient(
            base_url=settings.LMS_BASE_URL,
            headers={
                "Authorization": f"Bearer {settings.SERVICE_TOKEN}",
                "X-Service-Token": settings.SERVICE_TOKEN,
            },
            timeout=10.0,
        )
        self._perms_cache = TTLCache(maxsize=1000, ttl=300) # 5 minutes TTL
        self._lesson_context_cache = TTLCache(maxsize=5000, ttl=300) # 5 minutes TTL
        logger.info("LMS Client service ready ✅", base_url=settings.LMS_BASE_URL)

    async def get_user_permissions(self, user_id: str) -> UserPermissions:
        """
        Fetches the exact module, unit, and lesson permissions from the ERP.
        Uses TTLCache. Fails fast if the LMS is unreachable (Fail-Closed).
        """
        assert self._client is not None and self._perms_cache is not None, "LMSClientService not initialized"
        
        if user_id in self._perms_cache:
            return self._perms_cache[user_id]
        
        # 🧪 Standalone load testing / offline dev mode
        if settings.MOCK_LMS:
            perms = UserPermissions.model_validate({
                "userId": user_id,
                "accessibleModules": [
                    {"moduleId": "mod-erp-101", "levelFilters": [], "typeFilters": []},
                    {"moduleId": "53c15d6c-56b6-498b-bceb-57894530aa6e", "levelFilters": [], "typeFilters": []},
                ],
                "accessibleUnitIds": ["unit-01", "694265c4-26c4-44e6-8561-a3650513b02d"],
                "accessibleLessonIds": [],
            })
            self._perms_cache[user_id] = perms
            return perms

        # 🌐 Ask LMS for real-time permissions
        resp = await self._client.get(f"/api/internal/user-permissions/{user_id}")
        resp.raise_for_status()
        
        # Relying on Pydantic to do the alias mapping (camelCase to snake_case)
        perms = UserPermissions.model_validate(resp.json())
        self._perms_cache[user_id] = perms
        return perms

    async def get_lesson_full_context(self, lesson_id: str) -> LessonFullContext:
        """
        Fetches the full metadata (url, module, level, etc.) for a lesson.
        Cached in-memory via TTLCache (5 minutes) to eliminate internal LMS round-trip latency.
        Returns a validated LessonFullContext model supporting both camelCase and PascalCase.
        """
        assert self._client is not None and self._lesson_context_cache is not None, "LMSClientService not initialized"

        if lesson_id in self._lesson_context_cache:
            entry = self._lesson_context_cache[lesson_id]
            return entry if isinstance(entry, LessonFullContext) else LessonFullContext.model_validate(entry)

        resp = await self._client.get(f"/api/internal/lessons/{lesson_id}/full-context")
        resp.raise_for_status()
        context = LessonFullContext.model_validate(resp.json())
        self._lesson_context_cache[lesson_id] = context
        return context

    def invalidate_lesson_context(self, lesson_id: str) -> None:
        """Purges cached lesson context on LMS webhook updates."""
        if self._lesson_context_cache is not None:
            self._lesson_context_cache.pop(lesson_id, None)

    async def notify_lesson_ai_status(
        self,
        lesson_id: str,
        status: str,
        error: str | None = None,
        total_chunks: int = 0
    ) -> bool:
        """
        Sends an asynchronous webhook notification to the .NET LMS backend
        when audio ingestion completes or fails.
        Fails safely without raising unhandled exceptions (fire-and-forget / best-effort).
        """
        if not self._client:
            logger.warning("LMS client not initialized for status notification", lesson_id=lesson_id)
            return False

        payload = {
            "status": status,
            "chunks_count": total_chunks,
            "current_stage": "QDRANT_UPSERT_COMPLETE" if status == "Completed" else "PIPELINE_FAILED",
            "error": error,
            "lessonId": lesson_id,
            "totalChunks": total_chunks,
        }
        try:
            resp = await self._client.post(
                f"/api/internal/lessons/{lesson_id}/ai-status",
                json=payload
            )
            if resp.status_code in (200, 201, 202, 204):
                logger.info("Successfully notified LMS of AI status", lesson_id=lesson_id, status=status)
                return True
            else:
                logger.warning("LMS returned non-success for AI status notification", lesson_id=lesson_id, status_code=resp.status_code)
                return False
        except Exception as e:
            logger.warning("Failed to reach LMS for AI status notification", lesson_id=lesson_id, error=str(e))
            return False

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()

# Module-level singleton — initialize() called from lifespan
lms_client_service = LMSClientService()

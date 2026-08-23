import httpx
import structlog
from cachetools import TTLCache
from src.core.config import settings
from src.models.auth_models import UserPermissions

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

    def initialize(self) -> None:
        """Called from FastAPI lifespan — never in __init__."""
        self._client = httpx.AsyncClient(
            base_url=settings.LMS_BASE_URL,
            headers={"Authorization": f"Bearer {settings.SERVICE_TOKEN}"},
            timeout=10.0,
        )
        self._perms_cache = TTLCache(maxsize=1000, ttl=300) # 5 minutes TTL
        logger.info("LMS Client service ready ✅", base_url=settings.LMS_BASE_URL)

    async def get_user_permissions(self, user_id: str) -> UserPermissions:
        """
        Fetches the exact module, unit, and lesson permissions from the ERP.
        Uses TTLCache. Fails fast if the LMS is unreachable (Fail-Closed).
        """
        assert self._client is not None and self._perms_cache is not None, "LMSClientService not initialized"
        
        if user_id in self._perms_cache:
            return self._perms_cache[user_id]
        
        # 🌐 Ask LMS for real-time permissions
        resp = await self._client.get(f"/api/internal/user-permissions/{user_id}")
        resp.raise_for_status()
        
        # Relying on Pydantic to do the alias mapping (camelCase to snake_case)
        perms = UserPermissions.model_validate(resp.json())
        self._perms_cache[user_id] = perms
        return perms

    async def get_lesson_full_context(self, lesson_id: str) -> dict:
        """
        Fetches the full metadata (url, module, level, etc.) for a lesson.
        """
        assert self._client is not None, "LMSClientService not initialized"
        resp = await self._client.get(f"/api/internal/lessons/{lesson_id}/full-context")
        resp.raise_for_status()
        return resp.json()

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()

# Module-level singleton — initialize() called from lifespan
lms_client_service = LMSClientService()

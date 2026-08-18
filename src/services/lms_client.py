import httpx
import structlog
from src.core.config import settings
from src.models.auth_models import UserPermissions

logger = structlog.get_logger()

class LMSClient:
    """
    HTTP Client to securely communicate with the main .NET ERP Backend.
    Uses httpx.AsyncClient for high performance asynchronous requests.
    """
    def __init__(self):
        self._client: httpx.AsyncClient | None = None

    def initialize(self) -> None:
        self._client = httpx.AsyncClient(
            base_url=settings.LMS_BASE_URL,
            headers={"Authorization": f"Bearer {settings.SERVICE_TOKEN}"},
            timeout=10.0,
        )
        logger.info("LMS Client initialized ✅", base_url=settings.LMS_BASE_URL)

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()

    async def get_user_permissions(self, user_id: str) -> UserPermissions:
        """
        Fetches the exact module, unit, and lesson permissions from the ERP.
        Fails fast if the LMS is unreachable (Fail-Closed).
        """
        assert self._client is not None, "LMSClient is not initialized"
        
        # This calls the secure Internal endpoint on the .NET API
        resp = await self._client.get(f"/api/internal/user-permissions/{user_id}")
        resp.raise_for_status()
        
        # Relying on Pydantic to do the alias mapping (camelCase to snake_case)
        return UserPermissions.model_validate(resp.json())

lms_client = LMSClient()

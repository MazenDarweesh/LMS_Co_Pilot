# src/services/<name>_service.py
"""
<Name>Service — [Short description of what this service does]
================================================================
[Optional: explain the external dependency it wraps]
"""
import asyncio
import structlog
from src.core.config import settings

logger = structlog.get_logger()


class <Name>Service:
    def __init__(self):
        # Lazy initialization — do NOT load anything heavy here
        self._client = None  # type: ignore

    def initialize(self) -> None:
        """
        Called from FastAPI lifespan (src/db/session.py) — NEVER in __init__.
        Load models, create clients, validate config here.
        """
        # TODO: replace with actual initialization
        # self._client = SomeClient(api_key=settings.SOME_KEY)
        logger.info("<Name> service ready ✅")

    async def close(self) -> None:
        """Called on server shutdown — clean up resources."""
        if self._client is not None:
            # await self._client.aclose()  # uncomment if client has async close
            self._client = None


# Module-level singleton — initialize() called from lifespan
<name>_service = <Name>Service()

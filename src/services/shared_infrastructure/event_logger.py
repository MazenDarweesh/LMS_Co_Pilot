import structlog
import asyncpg
from src.core.config import settings

logger = structlog.get_logger()

class EventLoggerService:
    def __init__(self):
        self._pool: asyncpg.Pool | None = None

    def initialize(self, pool: asyncpg.Pool):
        """Initialized from FastAPI lifespan with the main db_pool."""
        self._pool = pool
        logger.info("Event Logger service ready ✅")

    async def log_event(self, session_id: str, agent_name: str, event_type: str, payload: dict) -> None:
        """
        Asynchronously writes agent events to PostgreSQL for full observability and Event Sourcing.
        """
        if not self._pool:
            logger.error("EventLoggerService not initialized")
            return
            
        query = """
            INSERT INTO agent_event_log (session_id, agent_name, event_type, payload)
            VALUES ($1, $2, $3, $4)
        """
        try:
            async with self._pool.acquire() as conn:
                # The payload dict is automatically converted to JSONB via our init_connection codec
                await conn.execute(query, session_id, agent_name, event_type, payload)
        except Exception as e:
            logger.error("Failed to log agent event", error=str(e), session_id=session_id)

# Module-level singleton
event_logger_service = EventLoggerService()

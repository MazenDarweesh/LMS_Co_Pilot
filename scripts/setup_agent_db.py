import asyncio
import structlog
from psycopg_pool import AsyncConnectionPool
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from src.core.config import settings

logger = structlog.get_logger()

async def setup_database():
    """
    Migration script to initialize LangGraph checkpoint tables.
    MUST be run once standalone, never during FastAPI lifespan to avoid race conditions.
    """
    logger.info("Connecting to PostgreSQL to setup LangGraph tables...", db=settings.DATABASE_URL)
    
    # Use autocommit=True for the pool to avoid transaction deadlocks
    async with AsyncConnectionPool(
        conninfo=settings.DATABASE_URL,
        max_size=5,
        kwargs={"autocommit": True}
    ) as pool:
        # Initialize the Saver with the connection pool
        checkpointer = AsyncPostgresSaver(pool)
        
        # This creates the necessary tables in Postgres if they don't exist
        await checkpointer.setup()
        
    logger.info("✅ LangGraph AsyncPostgresSaver tables created successfully.")

if __name__ == "__main__":
    asyncio.run(setup_database())

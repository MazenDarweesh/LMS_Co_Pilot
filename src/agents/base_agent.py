import asyncio
import structlog
from typing import TypedDict, Annotated, Sequence
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from psycopg_pool import AsyncConnectionPool
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from src.core.config import settings

logger = structlog.get_logger()

# Define the shared state schema for all LangGraph agents in this project
class AgentState(TypedDict):
    """
    State dictionary for the agents.
    The `add_messages` reducer ensures new messages are appended to the existing list.
    """
    messages: Annotated[Sequence[BaseMessage], add_messages]
    context: dict | None  # Used for passing retrieved RAG documents or user metadata

class AgentService:
    """
    Singleton service managing the LangGraph checkpointer (AsyncPostgresSaver)
    and its dedicated connection pool.
    """
    def __init__(self):
        self._pool: AsyncConnectionPool | None = None
        self.checkpointer: AsyncPostgresSaver | None = None

    async def initialize(self) -> None:
        """Called from FastAPI lifespan."""
        # 1. Create a dedicated connection pool for agents (autocommit=True is MANDATORY for Saver)
        self._pool = AsyncConnectionPool(
            conninfo=settings.DATABASE_URL,
            min_size=1,
            max_size=20,
            kwargs={"autocommit": True}
        )
        
        # Block lifespan until the connection pool is successfully opened (Fail-Fast)
        await self._pool.wait()
        
        # 2. Initialize the checkpointer using the pool
        self.checkpointer = AsyncPostgresSaver(self._pool)
        
        # 3. Create the LangGraph tables if they don't exist
        await self.checkpointer.setup()
        
        logger.info("Agent Service (LangGraph Checkpointer) ready ✅")

    async def close(self) -> None:
        """Clean shutdown of the connection pool."""
        if self._pool:
            await self._pool.close()

# Module-level singleton — initialize() called from lifespan
agent_service = AgentService()

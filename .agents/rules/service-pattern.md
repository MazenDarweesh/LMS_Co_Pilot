# Rule: Service Singleton + Lifespan Pattern

This rule is **always active**. All FastAPI services in `src/services/` MUST follow
this exact pattern. Never deviate from it.

## Mandatory Structure

Every service file MUST have these 4 elements:

```python
# 1. Structlog logger at module level
logger = structlog.get_logger()

# 2. Service class with lazy initialization
class MyService:
    def __init__(self):
        self._client = None  # ← lazy init, NOT loaded in __init__

    def initialize(self):
        """Called from FastAPI lifespan — NEVER in __init__."""
        self._client = create_client()
        logger.info("MyService ready ✅")

    async def close(self):
        """Called on server shutdown."""
        if self._client:
            await self._client.aclose()

# 3. Module-level singleton at BOTTOM of file
my_service = MyService()  # ← NOT initialized yet, just instantiated
```

## Registration in `src/db/session.py`

Every new service MUST be registered in the `lifespan()` async context manager,
BEFORE the `yield` statement:

```python
# In src/db/session.py — inside lifespan():
from src.services.my_service import my_service
my_service.initialize()          # or: await my_service.initialize() if async
app.state.my_service = my_service
logger.info("MyService ready ✅")

yield  # ← Application runs here

# After yield — cleanup:
await my_service.close()
```

## Rules

- ❌ NEVER load models or create clients in `__init__`
- ❌ NEVER use a global function instead of a class (no `def get_client(): ...` singletons)
- ❌ NEVER import a service and call methods without initializing it via lifespan
- ✅ ALWAYS use `app.state.<service_name>` to expose to request handlers if needed
- ✅ ALWAYS add a `close()` method even if it's a no-op (future-proofing)
- ✅ ALWAYS wrap CPU-bound operations (like loading ML models or running inference) in `asyncio.to_thread` to prevent blocking the FastAPI event loop.

## Existing Services Reference

| Service | Singleton | Pattern Type |
|:--------|:----------|:-------------|
| `embedding_service.py` | `embedding_service` | async initialize |
| `qdrant_service.py` | `qdrant_service` | async initialize |
| `reranker_service.py` | `reranker_service` | sync initialize |
| `search_service.py` | `search_service` | sync initialize |
| `auth_service.py` | `auth_service` | sync initialize |

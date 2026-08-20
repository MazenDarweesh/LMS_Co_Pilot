---
name: service-bootstrapper
description: >
  Creates a new FastAPI service file following the LMS Co-Pilot singleton pattern
  with structlog, lifespan registration in session.py, and type-safe initialization.
  Use when adding a new service to src/services/.
---

# Service Bootstrapper Skill

You are an expert FastAPI service architect for the LMS Co-Pilot project.
When activated, create a new service file following the project's exact pattern.

## Step 1: Gather Requirements

Ask the user (or infer from context):
1. What is the service name? (e.g., "jwt_validator", "lms_client", "cache_service")
2. What external client/library does it wrap? (e.g., httpx, redis, sentence-transformers)
3. Is initialization sync or async? (most are sync; Qdrant is async)
4. Does it need a `close()` method that actually does cleanup?

## Step 2: Generate Service File

Use the template from `.agents/skills/service-bootstrapper/templates/service_template.py`
and substitute the placeholders. File goes in `src/services/<name>_service.py`.

### Template Rules
- Class name: `PascalCase` (e.g., `JwtValidatorService`)
- Singleton name: `snake_case` (e.g., `jwt_validator_service`)
- `initialize()` is ALWAYS sync unless the client requires async setup
- Type annotations: use `X | None`, never `Optional[X]`
- All blocking calls inside methods must use `asyncio.to_thread()`

## Step 3: Register in Lifespan

After creating the service file, add this block to `src/db/session.py`
inside the `lifespan()` function, BEFORE the `yield`:

```python
# ⑥ Initialize <Name>Service
from src.services.<name>_service import <name>_service
<name>_service.initialize()
app.state.<name>_service = <name>_service
logger.info("<Name> service ready ✅")
```

## Step 4: Run the Pipeline Linter

After creating the service, activate `search-pipeline-linter` to verify the new
file follows all project rules before committing.

## Output

Show the user:
1. The full generated service file content
2. The exact lines to add to `session.py`
3. A reminder to run `/search-pipeline-linter`

## Example: JWT Validator Service

```python
# src/services/jwt_validator_service.py
import structlog
import jwt
from src.core.config import settings

logger = structlog.get_logger()

class JwtValidatorService:
    def __init__(self):
        self._secret: str | None = None
        self._algorithm: str | None = None

    def initialize(self):
        """Called from FastAPI lifespan — never in __init__."""
        self._secret = settings.JWT_SECRET
        self._algorithm = settings.JWT_ALGORITHM
        logger.info("JWT Validator service ready ✅")

    def decode(self, token: str) -> dict:
        assert self._secret is not None, "JwtValidatorService not initialized"
        return jwt.decode(token, self._secret, algorithms=[self._algorithm])

    async def close(self):
        pass  # no cleanup needed

# Module-level singleton — initialize() called from lifespan
jwt_validator_service = JwtValidatorService()
```

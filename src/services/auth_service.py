import jwt
from pydantic import ValidationError
import structlog
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from src.core.config import settings
from src.models.auth_models import TokenClaims, UserPermissions, UserContext
from src.services.lms_client import lms_client_service

logger = structlog.get_logger()
bearer_scheme = HTTPBearer()

class AuthValidatorService:
    def __init__(self):
        self._secret: str | None = None
        self._algorithm: str | None = None

    def initialize(self):
        """Called from FastAPI lifespan — never in __init__."""
        self._secret = settings.JWT_SECRET
        self._algorithm = settings.JWT_ALGORITHM
        logger.info("Auth Validator service ready ✅")

    def decode_jwt(self, token: str) -> TokenClaims:
        """Decodes JWT with strict verification enabled (issuer & audience)."""
        assert self._secret is not None, "AuthValidatorService not initialized"
        try:
            payload = jwt.decode(
                token,
                self._secret,
                algorithms=[self._algorithm],
                audience=settings.JWT_AUDIENCE or None,
                issuer=settings.JWT_ISSUER or None,
            )
            return TokenClaims.model_validate(payload)
        except jwt.ExpiredSignatureError:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token expired")
        except (jwt.InvalidTokenError, ValidationError) as e:
            logger.error("Invalid JWT provided or claims validation failed", error=str(e))
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"Invalid token: {str(e)}")
            
    async def close(self):
        pass

# Module-level singleton — initialize() called from lifespan
auth_validator_service = AuthValidatorService()

def _build_user_entities(claims: TokenClaims, perms: UserPermissions) -> list[str]:
    """
    Constructs the precise list of Qdrant filtering entities.
    - Enforces strict Level & Type filtering for modules.
    - Grants standalone and playlist global access ONLY to Admins.
    """
    entities: list[str] = [
        f"tenant:{claims.company_id}",
        f"role:{claims.role}",
    ]
    
    # 🔴 GAP 2/3 FIX: Standalone & Playlists are restricted to Admins only.
    if claims.role == "Admin":
        entities.append("content:standalone")
        entities.append("content:playlist")

    # 🔴 GAP 1 FIX: Strict Level & Type Filters per Module
    for mod in perms.accessible_modules:
        entities.append(f"module:{mod.module_id}")

    # Standard unit and lesson access
    for uid in perms.accessible_unit_ids:
        entities.append(f"unit:{uid}")
    for lid in perms.accessible_lesson_ids:
        entities.append(f"lesson:{lid}")

    return entities

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> UserContext:
    token = credentials.credentials
    claims = auth_validator_service.decode_jwt(token)

    try:
        # Caching is now handled directly by TTLCache inside lms_client_service
        perms = await lms_client_service.get_user_permissions(claims.user_id)
    except Exception as e:
        logger.error("LMS connection failed", user_id=claims.user_id, error=str(e))
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Auth service unavailable")

    entities = _build_user_entities(claims, perms)
    return UserContext(claims=claims, permissions=perms, user_entities=entities)

def require_role(*roles: str):
    """Dependency to restrict API routes to certain roles (e.g. Admin only)."""
    async def _check(ctx: UserContext = Depends(get_current_user)) -> UserContext:
        if ctx.claims.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient permissions for this action")
        return ctx
    return _check

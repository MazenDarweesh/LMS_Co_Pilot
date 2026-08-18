import time
import jwt
import structlog
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from src.core.config import settings
from src.models.auth_models import TokenClaims, UserPermissions, UserContext
from src.services.lms_client import lms_client

logger = structlog.get_logger()
bearer_scheme = HTTPBearer()

def _decode_jwt(token: str) -> TokenClaims:
    """Decodes JWT with strict verification enabled (issuer & audience)."""
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
            audience=settings.JWT_AUDIENCE or None,
            issuer=settings.JWT_ISSUER or None,
        )
        return TokenClaims.model_validate(payload)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token expired")
    except jwt.InvalidTokenError as e:
        logger.error("Invalid JWT provided", error=str(e))
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token")

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
        for lvl in mod.level_filters:
            entities.append(f"level:{lvl}")
        for typ in mod.type_filters:
            entities.append(f"type:{typ}")

    # Standard unit and lesson access
    for uid in perms.accessible_unit_ids:
        entities.append(f"unit:{uid}")
    for lid in perms.accessible_lesson_ids:
        entities.append(f"lesson:{lid}")

    return entities

async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> UserContext:
    token = credentials.credentials
    claims = _decode_jwt(token)

    # In-Memory Cache (TTL: 1 minute to reduce staleness. Prepared for future Redis swap).
    cache = getattr(request.app.state, "permissions_cache", {})
    cache_key = claims.user_id
    now = time.monotonic()
    
    if not hasattr(request.app.state, "permissions_cache"):
        request.app.state.permissions_cache = cache

    if cache_key in cache:
        cached_perms, cached_at = cache[cache_key]
        if now - cached_at < 60: # 1 minute TTL
            entities = _build_user_entities(claims, cached_perms)
            return UserContext(claims=claims, permissions=cached_perms, user_entities=entities)

    try:
        # 🌐 Ask LMS for real-time permissions
        perms = await lms_client.get_user_permissions(claims.user_id)
    except Exception as e:
        logger.error("LMS connection failed", error=str(e))
        # 🔴 GAP 4 FIX: Fail-Closed Strategy
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Auth service unavailable")

    cache[cache_key] = (perms, now)
    entities = _build_user_entities(claims, perms)
    return UserContext(claims=claims, permissions=perms, user_entities=entities)

def require_role(*roles: str):
    """Dependency to restrict API routes to certain roles (e.g. Admin only)."""
    async def _check(ctx: UserContext = Depends(get_current_user)) -> UserContext:
        if ctx.claims.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient permissions for this action")
        return ctx
    return _check

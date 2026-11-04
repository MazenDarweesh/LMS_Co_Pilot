# ─── Windows ProactorEventLoop Fix ───────────────────────────────────────────
# MUST be before any asyncio/psycopg imports to take effect.
import sys
import asyncio

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# ─── Standard Library ─────────────────────────────────────────────────────────
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

# ─── Third-Party ──────────────────────────────────────────────────────────────
import jwt
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

# ─── Local ────────────────────────────────────────────────────────────────────
from src.main import app
from src.core.config import settings
from src.models.auth_models import UserPermissions


# ─── JWT Token Factory ────────────────────────────────────────────────────────
def make_jwt_token(
    role: str = "Admin",
    user_id: str = "test-user-01",
    company_id: str = "test-co",
) -> str:
    """
    ينشئ JWT حقيقي موقّع بنفس السر المستخدم في التطبيق.
    يُستخدم في كل اختبار يحتاج Authorization header.
    """
    payload = {
        "Id": user_id,
        "Role": role,
        "CompanyId": company_id,
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
    }
    if settings.JWT_ISSUER:
        payload["iss"] = settings.JWT_ISSUER
    if settings.JWT_AUDIENCE:
        payload["aud"] = settings.JWT_AUDIENCE

    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


# ─── Mock Helpers (module-level for reuse and readability) ────────────────────
def make_mock_permissions(user_id: str = "test-user-01") -> UserPermissions:
    """بيانات صلاحيات وهمية تُعاد بدلاً من استدعاء LMS API الحقيقي."""
    return UserPermissions.model_validate({
        "userId": user_id,
        "accessibleModules": [
            {"moduleId": "mod-erp-101", "levelFilters": [], "typeFilters": []}
        ],
        "accessibleUnitIds": ["unit-01"],
        "accessibleLessonIds": ["lesson-001"],
    })


async def _mock_call_model(self, state: dict) -> dict:
    """
    Replaces SearchService._call_model to skip the real LLM (Gemini) call.
    Returns a valid JSON string that matches the SearchResponse schema.
    Uses json.dumps to safely serialize the answer — avoids broken f-strings
    if the query contains curly braces.
    """
    from langchain_core.messages import AIMessage

    messages = state.get("messages", [])
    query = messages[0].content if messages else "test query"
    mock_answer = json.dumps({
        "answer": "هذه إجابة تجريبية سريعة جداً. نظام ERP هو...",
        "sources": [],
        "query_used": query,
    }, ensure_ascii=False)
    return {"messages": [AIMessage(content=mock_answer)]}


async def _mock_rerank(self, query: str, passages: list, top_n: int = 5, **kwargs) -> list:
    """
    Replaces RerankerService.rerank to skip the slow BAAI/bge-reranker-v2-m3 model (~70s on CPU).
    Simply returns the top N documents unchanged — order is irrelevant in tests.
    """
    return passages[:top_n]


# ─── Main Async Client Fixture ────────────────────────────────────────────────
@pytest_asyncio.fixture(scope="session")
async def async_client():
    """
    يُشغّل FastAPI مع lifespan كامل (DB + Qdrant + LangGraph).
    يعمل مع Docker Compose — تأكد من تشغيل: docker compose up -d

    Mocked services (for speed and cost):
      - LMS Client  → make_mock_permissions() بدلاً من استدعاء .NET
      - LLM         → _mock_call_model() بدلاً من Gemini API
      - Reranker    → _mock_rerank() بدلاً من BAAI/bge-reranker-v2-m3
    """
    patch_lms = patch(
        "src.services.lms_bridge.lms_client.lms_client_service.get_user_permissions",
        new_callable=AsyncMock,
        return_value=make_mock_permissions(),
    )
    patch_llm = patch(
        "src.services.cognitive_search.search_service.SearchService._call_model",
        new=_mock_call_model,
    )
    patch_reranker = patch(
        "src.services.cognitive_search.reranker_service.RerankerService.rerank",
        new=_mock_rerank,
    )

    with patch_lms, patch_llm, patch_reranker:
        async with app.router.lifespan_context(app):
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://localhost",
                timeout=30.0,
            ) as client:
                yield client


# ─── Auth Header Fixtures ─────────────────────────────────────────────────────
@pytest.fixture
def admin_headers() -> dict:
    """Authorization headers لمستخدم Admin."""
    return {"Authorization": f"Bearer {make_jwt_token(role='Admin')}"}


@pytest.fixture
def student_headers() -> dict:
    """Authorization headers لمستخدم Student."""
    return {"Authorization": f"Bearer {make_jwt_token(role='Student')}"}

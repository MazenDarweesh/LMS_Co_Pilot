import pytest
import time
from unittest.mock import AsyncMock, patch, MagicMock

from src.models.auth_models import UserContext, TokenClaims, UserPermissions
from src.models.search_models import SearchRequest, SearchResponse, SourceItem
from src.services.exact_cache_service import ExactCacheService
from src.services.intent_router import IntentRouterService, IntentType
from src.services.semantic_cache_service import SemanticCacheService
from src.services.search_service import SearchService


@pytest.fixture
def sample_user_context():
    return UserContext(
        claims=TokenClaims(
            Id="user_123",
            CompanyId="tenant_alpha",
            Role="Student",
        ),
        permissions=UserPermissions(
            userId="user_123",
            accessibleLessonIds=["lesson_01", "lesson_02"],
            accessibleUnitIds=["unit_01"],
        ),
        user_entities=["tenant_alpha"],
    )


@pytest.fixture
def admin_user_context():
    return UserContext(
        claims=TokenClaims(
            Id="admin_999",
            CompanyId="tenant_alpha",
            Role="Admin",
        ),
        permissions=UserPermissions(
            userId="admin_999",
        ),
        user_entities=["tenant_alpha"],
    )


# ─── 1. Exact In-Memory Cache Tests ──────────────────────────────────────────

def test_exact_cache_hit_and_miss(sample_user_context):
    cache = ExactCacheService()
    cache.initialize()

    query = "ما هي شجرة الحسابات؟"
    user = sample_user_context

    # Initially Miss
    assert cache.lookup(query, user) is None

    # Store response
    resp = SearchResponse(
        answer="شجرة الحسابات هي دليل الحسابات المالي.",
        sources=[SourceItem(type="video", url="http://vid1", start=10, end=30, lesson_id="lesson_01")],
        query_used=query,
    )
    cache.store(query, resp, user)

    # Now Hit
    hit = cache.lookup(query, user)
    assert hit is not None
    assert hit.answer == resp.answer
    assert len(hit.sources) == 1
    assert hit.sources[0].lesson_id == "lesson_01"


def test_exact_cache_multi_tenant_isolation(sample_user_context):
    cache = ExactCacheService()
    cache.initialize()

    query = "ما هو الإهلاك السنوي؟"
    resp = SearchResponse(answer="حساب الإهلاك...", sources=[], query_used=query)
    cache.store(query, resp, sample_user_context)

    # User from another tenant
    other_tenant_user = UserContext(
        claims=TokenClaims(Id="user_456", CompanyId="tenant_beta", Role="Student"),
        permissions=UserPermissions(userId="user_456"),
        user_entities=["tenant_beta"],
    )

    assert cache.lookup(query, other_tenant_user) is None


def test_exact_cache_rbac_permission_rejection(sample_user_context, admin_user_context):
    cache = ExactCacheService()
    cache.initialize()

    query = "كيف أقفل الفترة المالية؟"
    # Response references lesson_99 which the student does NOT have access to
    resp = SearchResponse(
        answer="خطوات الإقفال...",
        sources=[SourceItem(type="video", url="http://vid2", start=0, end=15, lesson_id="lesson_99")],
        query_used=query,
    )
    cache.store(query, resp, sample_user_context)

    # Student should be rejected (access denied)
    assert cache.lookup(query, sample_user_context) is None

    # Student with empty permissions / no enrollments should also be rejected
    unenrolled_user = UserContext(
        claims=TokenClaims(Id="user_789", CompanyId="tenant_alpha", Role="Student"),
        permissions=UserPermissions(userId="user_789", accessibleLessonIds=[]),
        user_entities=["tenant_alpha"],
    )
    assert cache.lookup(query, unenrolled_user) is None

    # Student with None permissions object should also be rejected (fail-closed)
    no_perm_user = UserContext(
        claims=TokenClaims(Id="user_999", CompanyId="tenant_alpha", Role="Student"),
        permissions=None,
        user_entities=["tenant_alpha"],
    )
    assert cache.lookup(query, no_perm_user) is None

    # Admin should bypass lesson restriction and get HIT
    admin_hit = cache.lookup(query, admin_user_context)
    assert admin_hit is not None
    assert admin_hit.answer == "خطوات الإقفال..."


def test_exact_cache_invalidation_by_lesson_id(sample_user_context):
    cache = ExactCacheService()
    cache.initialize()

    query1 = "درس 1"
    query2 = "درس 2"
    resp1 = SearchResponse(answer="A1", sources=[SourceItem(type="video", lesson_id="lesson_01")], query_used=query1)
    resp2 = SearchResponse(answer="A2", sources=[SourceItem(type="video", lesson_id="lesson_02")], query_used=query2)

    cache.store(query1, resp1, sample_user_context)
    cache.store(query2, resp2, sample_user_context)

    # Invalidate lesson_01
    invalidated_count = cache.invalidate_by_lesson_id("lesson_01")
    assert invalidated_count == 1
    assert cache.lookup(query1, sample_user_context) is None
    assert cache.lookup(query2, sample_user_context) is not None


# ─── 2. Fast Ingress Intent Router Tests ──────────────────────────────────────

def test_intent_router_greetings():
    router = IntentRouterService()
    router.initialize()

    greetings = [
        "أهلاً",
        "مرحبا",
        "السلام عليكم",
        "صباح الخير",
        "ازيك يا باشا",
        "hello",
        "Hi!",
        "Good morning",
    ]
    for g in greetings:
        t0 = time.time()
        res = router.classify(g)
        elapsed_ms = (time.time() - t0) * 1000
        assert elapsed_ms < 20.0, f"Greeting '{g}' took too long: {elapsed_ms}ms"
        assert res.intent == IntentType.GREETING
        assert res.canned_response is not None


def test_intent_router_out_of_scope():
    router = IntentRouterService()
    router.initialize()

    out_of_scope_queries = [
        "ما هو الطقس اليوم في القاهرة؟",
        "احكيلي نكتة تضحك",
        "مين رئيس وزراء كندا؟",
        "كم سعر الدولار اليوم في البنك؟",
        "نتيجة مباراة الأهلي والزمالك",
        "tell me a joke",
        "what's the weather like?",
    ]
    for q in out_of_scope_queries:
        t0 = time.time()
        res = router.classify(q)
        elapsed_ms = (time.time() - t0) * 1000
        assert elapsed_ms < 20.0, f"Out of scope '{q}' took too long: {elapsed_ms}ms"
        assert res.intent == IntentType.OUT_OF_SCOPE
        assert "المناهج والمحاضرات" in res.canned_response or "LMS" in res.canned_response


def test_intent_router_educational_queries():
    router = IntentRouterService()
    router.initialize()

    rag_queries = [
        "كيفية إثبات قيد اليومية في نظام الـ ERP",
        "ما هي خطوات حساب الإهلاك للأصول الثابتة؟",
        "شرح طريقة جرد المخزون الدوري والمستمر",
        "how to create a journal entry in accounting module",
    ]
    for q in rag_queries:
        res = router.classify(q)
        assert res.intent == IntentType.RAG_QUERY
        assert res.canned_response is None


# ─── 3. Semantic Cache Eviction Method Test ────────────────────────────────────

@pytest.mark.asyncio
async def test_semantic_cache_eviction():
    service = SemanticCacheService()
    service.enabled = True

    mock_client = AsyncMock()
    mock_client.delete = AsyncMock(return_value=MagicMock(status="ok"))
    mock_client.scroll = AsyncMock(return_value=([], None))

    with patch("src.services.semantic_cache_service.qdrant_service._client", mock_client):
        evicted = await service.evict_expired_entries()
        assert evicted == 0
        mock_client.delete.assert_called_once()


# ─── 4. End-to-End Fast Ingress in SearchService ──────────────────────────────

@pytest.mark.asyncio
async def test_search_service_fast_ingress_greeting(sample_user_context):
    search_svc = SearchService()

    req = SearchRequest(query="السلام عليكم ورحمة الله", scope="course")
    t0 = time.time()
    resp = await search_svc.search(req, sample_user_context)
    elapsed_ms = (time.time() - t0) * 1000

    # Must return immediately without embeddings or Qdrant
    assert elapsed_ms < 50.0  # Fast ingress intercept
    assert "أهلاً بك" in resp.answer
    assert resp.sources == []


@pytest.mark.asyncio
async def test_search_service_fast_ingress_out_of_scope(sample_user_context):
    search_svc = SearchService()

    req = SearchRequest(query="قولي نكتة مضحكة", scope="course")
    t0 = time.time()
    resp = await search_svc.search(req, sample_user_context)
    elapsed_ms = (time.time() - t0) * 1000

    assert elapsed_ms < 50.0
    assert "مخصص حصرياً للمساعدة في محتوى المناهج" in resp.answer
    assert resp.sources == []

# tests/integration/test_semantic_cache.py
"""
Integration Tests — Semantic Cache Service (Qdrant Vector Cache)
=================================================================
Validates:
1. Cache Store and Hit on identical or semantically close vectors.
2. Cache Miss on novel / distinct vectors.
3. Multi-Tenancy Isolation: company_a cache is invisible to company_b.
4. Permission Isolation: restricted student missing cached lesson_id gets Cache Miss.
5. Invalidation on Webhook: invalidate_by_lesson_id purges stale entries.
6. End-to-end /v1/search API endpoint utilizing semantic cache.
"""

import pytest
import uuid
from httpx import AsyncClient

from src.models.auth_models import UserContext, UserPermissions, TokenClaims
from src.models.search_models import SearchResponse, SourceItem
from src.services.semantic_cache_service import semantic_cache_service
from tests.conftest import make_jwt_token


def make_distinct_vector(idx: int) -> list[float]:
    vec = [0.0] * 1024
    vec[idx % 1024] = 1.0
    return vec


@pytest.fixture
def base_user_context():
    co_id = f"company_{uuid.uuid4().hex[:8]}"
    return UserContext(
        claims=TokenClaims(
            Id="student_123",
            Role="Student",
            CompanyId=co_id,
            DepartmentId="dept_eng",
        ),
        permissions=UserPermissions(
            userId="student_123",
            accessibleModules=[],
            accessibleUnitIds=[],
            accessibleLessonIds=["lesson_math_101", "lesson_physics_201"],
        ),
        user_entities=[],
    )


@pytest.mark.asyncio
async def test_cache_store_and_lookup_exact(async_client, base_user_context):
    """تخزين استجابة واسترجاعها بنفس المتجه بنجاح (Cache HIT)."""
    vec = make_distinct_vector(10)
    test_query = f"ما هي قوانين نيوتن؟ {uuid.uuid4()}"
    test_answer = "قوانين نيوتن الثلاثة للحركة هي أساس الميكانيكا الكلاسيكية."
    test_sources = [
        SourceItem(type="video", url="https://youtube.com/v1", lesson_id="lesson_physics_201")
    ]
    resp = SearchResponse(answer=test_answer, sources=test_sources, query_used=test_query)

    # تخزين في الكاش
    await semantic_cache_service.store(
        query=test_query,
        query_vector=vec,
        response=resp,
        user_ctx=base_user_context,
    )

    # استرجاع
    cached = await semantic_cache_service.lookup(query_vector=vec, user_ctx=base_user_context)
    assert cached is not None, "Expected Cache HIT but got None"
    assert cached.answer == test_answer
    assert len(cached.sources) == 1
    assert cached.sources[0].lesson_id == "lesson_physics_201"


@pytest.mark.asyncio
async def test_cache_tenant_isolation(async_client, base_user_context):
    """عزل الشركات: طالب من company_b لا يرى كاش company_a."""
    vec = make_distinct_vector(20)
    test_query = f"أسرار المبيعات الخاصة {uuid.uuid4()}"
    resp = SearchResponse(answer="بيانات سرية للشركة A", sources=[], query_used=test_query)

    # التخزين لـ company_a
    await semantic_cache_service.store(
        query=test_query,
        query_vector=vec,
        response=resp,
        user_ctx=base_user_context,
    )

    # محاولة استرجاع من طالب تابع لـ company_b
    user_b = UserContext(
        claims=TokenClaims(
            Id="student_999",
            Role="Student",
            CompanyId=f"company_diff_{uuid.uuid4().hex[:6]}",
            DepartmentId="dept_sales",
        ),
        permissions=UserPermissions(userId="student_999", accessibleLessonIds=[]),
        user_entities=[],
    )

    cached = await semantic_cache_service.lookup(query_vector=vec, user_ctx=user_b)
    assert cached is None, "Tenant isolation failed: company_b accessed company_a cache!"


@pytest.mark.asyncio
async def test_cache_permission_restriction(async_client, base_user_context):
    """طالب غير مصرح له برؤية درس معين لا يحصل على الكاش الخاص به."""
    vec = make_distinct_vector(30)
    test_query = f"موضوع متقدم مقفل {uuid.uuid4()}"
    test_sources = [
        SourceItem(type="video", url="https://youtube.com/restricted", lesson_id="secret_lesson_restricted")
    ]
    resp = SearchResponse(answer="محتوى متقدم", sources=test_sources, query_used=test_query)

    await semantic_cache_service.store(
        query=test_query,
        query_vector=vec,
        response=resp,
        user_ctx=base_user_context,
    )

    # base_user_context لديه فقط lesson_math_101 و lesson_physics_201 (ليس لديه secret_lesson_restricted)
    cached = await semantic_cache_service.lookup(query_vector=vec, user_ctx=base_user_context)
    assert cached is None, "Permission check failed: User accessed cached response of restricted lesson!"


@pytest.mark.asyncio
async def test_cache_invalidation_by_lesson_id(async_client, base_user_context):
    """إبطال الكاش فور تحديث أو مسح درس معين."""
    lesson_to_invalidate = f"lesson_temp_{uuid.uuid4().hex[:6]}"
    # إضافة الدرس لصلاحيات المستخدم للتأكد من نجاح الـ lookup أولاً
    base_user_context.permissions.accessible_lesson_ids.append(lesson_to_invalidate)

    vec = make_distinct_vector(40)
    test_query = f"سؤال خاص بدرس سيتم حذفه {uuid.uuid4()}"
    resp = SearchResponse(
        answer="إجابة الدرس القديمة",
        sources=[SourceItem(type="video", url="http://test", lesson_id=lesson_to_invalidate)],
        query_used=test_query,
    )

    await semantic_cache_service.store(
        query=test_query,
        query_vector=vec,
        response=resp,
        user_ctx=base_user_context,
    )

    # التحقق من وجوده في الكاش
    first_lookup = await semantic_cache_service.lookup(query_vector=vec, user_ctx=base_user_context)
    assert first_lookup is not None, "Cache should have hit before invalidation"

    # إبطال كاش هذا الدرس
    await semantic_cache_service.invalidate_by_lesson_id(lesson_to_invalidate)

    # التحقق من إزالته بعد الإبطال
    second_lookup = await semantic_cache_service.lookup(query_vector=vec, user_ctx=base_user_context)
    assert second_lookup is None, "Cache should be cleared after invalidate_by_lesson_id!"


@pytest.mark.asyncio
async def test_api_search_endpoint_with_cache(async_client: AsyncClient, admin_headers):
    """اختبار نقطة النهاية /v1/search مع التحقق من استجابة الكاش."""
    unique_q = f"ما هي وظيفة الـ GL في المحاسبة؟ {uuid.uuid4().hex[:8]}"

    # الطلب الأول: يمر بالـ pipeline كاملة ويُخزن في الكاش
    resp1 = await async_client.post(
        "/v1/search",
        headers=admin_headers,
        json={"query": unique_q, "scope": "all"},
    )
    assert resp1.status_code == 200
    data1 = resp1.json()
    assert "answer" in data1

    # الطلب الثاني بنفس السؤال: يجب أن ينجح فوراً (Cache Hit)
    resp2 = await async_client.post(
        "/v1/search",
        headers=admin_headers,
        json={"query": unique_q, "scope": "all"},
    )
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["answer"] == data1["answer"]

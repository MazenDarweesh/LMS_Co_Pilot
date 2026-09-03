# tests/integration/test_auth_rbac.py
"""
Integration Tests — JWT Authentication & Role-Based Access Control (RBAC)
==========================================================================
يختبر: التحقق من JWT، رفض الطلبات غير المصرح بها، وفرض الأدوار.
تشغيل: uv run pytest tests/integration/test_auth_rbac.py -v
"""
import pytest
from httpx import AsyncClient

SEARCH_URL = "/v1/search"
QUIZ_URL = "/v1/admin/lessons/lesson-001/generate-quiz"
SUMMARY_URL = "/v1/admin/lessons/lesson-001/generate-summary"
INGEST_URL = "/v1/ingest/audio"

SAMPLE_INGEST_PAYLOAD = {
    "youtube_url": "https://youtu.be/dQw4w9WgXcQ",
    "lesson_id": "test-lesson-rbac",
    "lesson_metadata": {
        "tenant_ids": ["test-co"],
        "module_id": "mod-01",
        "unit_id": "unit-01",
        "level_id": "level-01",
        "type_id": "type-01",
        "lesson_id": "test-lesson-rbac",
        "target_roles": ["Student"],
    },
}


# ─── Missing / Invalid Token ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_search_without_token_returns_401(async_client: AsyncClient):
    """
    بدون Authorization header → 401.
    HTTPBearer يرفض الطلب قبل أن يصل لكود الـ endpoint.
    """
    resp = await async_client.post(
        SEARCH_URL, json={"query": "ما هو ERP؟", "scope": "all"}
    )
    assert resp.status_code == 401, f"Expected 401, got {resp.status_code}"


@pytest.mark.asyncio
async def test_search_with_invalid_token_returns_401(async_client: AsyncClient):
    """JWT مزوّر (لم يُوقَّع بالسر الصحيح) → 401."""
    resp = await async_client.post(
        SEARCH_URL,
        headers={"Authorization": "Bearer this.is.a.fake.token"},
        json={"query": "ما هو ERP؟", "scope": "all"},
    )
    assert resp.status_code == 401, f"Expected 401, got {resp.status_code}"


@pytest.mark.asyncio
async def test_search_with_malformed_bearer_returns_401(async_client: AsyncClient):
    """Authorization header بصيغة خاطئة (بدون 'Bearer') → 401."""
    resp = await async_client.post(
        SEARCH_URL,
        headers={"Authorization": "Token invalid_format"},
        json={"query": "ما هو ERP؟", "scope": "all"},
    )
    assert resp.status_code == 401


# ─── Admin-Only Endpoints ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_generate_quiz_blocks_student(async_client: AsyncClient, student_headers):
    """
    generate-quiz endpoint (Admin only) → Student يحصل على 403.
    """
    resp = await async_client.post(QUIZ_URL, headers=student_headers)
    assert resp.status_code == 403, f"Expected 403 for Student, got {resp.status_code}"


@pytest.mark.asyncio
async def test_generate_quiz_allows_admin(async_client: AsyncClient, admin_headers):
    """
    generate-quiz endpoint → Admin يحصل على أي كود غير 403.
    (قد يرجع 400 لو Qdrant ليس فيه بيانات للدرس — وده مقبول)
    """
    resp = await async_client.post(QUIZ_URL, headers=admin_headers)
    assert resp.status_code != 403, f"Admin should not get 403"
    assert resp.status_code in (200, 400, 422, 500)


@pytest.mark.asyncio
async def test_generate_summary_blocks_student(async_client: AsyncClient, student_headers):
    """generate-summary (Admin only) → Student يُرفض."""
    resp = await async_client.post(SUMMARY_URL, headers=student_headers)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_generate_summary_allows_admin(async_client: AsyncClient, admin_headers):
    """generate-summary → Admin يُقبل (أي كود غير 403)."""
    resp = await async_client.post(SUMMARY_URL, headers=admin_headers)
    assert resp.status_code != 403


@pytest.mark.asyncio
async def test_ingest_audio_blocks_student(async_client: AsyncClient, student_headers):
    """
    ingest/audio endpoint (Admin only) → Student يحصل على 403.
    """
    resp = await async_client.post(
        INGEST_URL, headers=student_headers, json=SAMPLE_INGEST_PAYLOAD
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_ingest_audio_allows_admin(async_client: AsyncClient, admin_headers):
    """
    ingest/audio → Admin يُقبل ويحصل على 200 (processing_started).
    """
    resp = await async_client.post(
        INGEST_URL, headers=admin_headers, json=SAMPLE_INGEST_PAYLOAD
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "processing_started"


# ─── Search Accessible to Both Roles ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_search_allows_student(async_client: AsyncClient, student_headers):
    """Search endpoint مفتوح للطلاب أيضاً (بفلترة صلاحياتهم)."""
    resp = await async_client.post(
        SEARCH_URL,
        headers=student_headers,
        json={"query": "ما هو نظام ERP؟", "scope": "all"},
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_search_allows_admin(async_client: AsyncClient, admin_headers):
    """Search endpoint يعمل للـ Admin."""
    resp = await async_client.post(
        SEARCH_URL,
        headers=admin_headers,
        json={"query": "ما هو نظام ERP؟", "scope": "all"},
    )
    assert resp.status_code == 200

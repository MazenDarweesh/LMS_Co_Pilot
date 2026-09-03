# tests/integration/test_search_rag.py
"""
Integration Tests — Hybrid RAG Search + LangGraph Conversational Memory
========================================================================
يحتاج: docker compose up -d (Qdrant + PostgreSQL)
يحتاج: بيانات في Qdrant (درس مُدمج مسبقاً)
تشغيل: uv run pytest tests/integration/test_search_rag.py -v
"""
import pytest
from httpx import AsyncClient

SEARCH_URL = "/v1/search"
THREAD_A = "test-memory-thread-AAA"  # thread لاختبار الذاكرة
THREAD_B = "test-isolated-thread-BBB"  # thread معزول


# ─── Schema Validation ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_search_returns_valid_schema(async_client: AsyncClient, admin_headers):
    """الـ Response يجب أن يطابق SearchResponse schema تماماً."""
    resp = await async_client.post(
        SEARCH_URL,
        headers=admin_headers,
        json={"query": "ما هو نظام ERP؟", "scope": "all"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "answer" in data, "Missing 'answer' field"
    assert "sources" in data, "Missing 'sources' field"
    assert "query_used" in data, "Missing 'query_used' field"
    assert isinstance(data["sources"], list), "'sources' must be a list"


@pytest.mark.asyncio
async def test_search_answer_is_not_empty(async_client: AsyncClient, admin_headers):
    """الإجابة لا يجب أن تكون فارغة أو أقل من 10 أحرف."""
    resp = await async_client.post(
        SEARCH_URL,
        headers=admin_headers,
        json={"query": "ما هو بدء التشغيل؟", "scope": "all"},
    )
    assert resp.status_code == 200
    answer = resp.json()["answer"]
    assert len(answer) > 10, f"Answer too short: '{answer}'"


@pytest.mark.asyncio
async def test_search_query_used_matches_input(async_client: AsyncClient, admin_headers):
    """الـ query_used في الاستجابة يجب أن يطابق الاستعلام المُرسَل."""
    query = "ما هو موديول الـ Inventory؟"
    resp = await async_client.post(
        SEARCH_URL,
        headers=admin_headers,
        json={"query": query, "scope": "all"},
    )
    assert resp.status_code == 200
    assert resp.json()["query_used"] == query


# ─── Input Validation (Pydantic) ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_search_rejects_query_too_short(async_client: AsyncClient, admin_headers):
    """استعلام أقل من حرفين → 422 Unprocessable Entity."""
    resp = await async_client.post(
        SEARCH_URL,
        headers=admin_headers,
        json={"query": "أ", "scope": "all"},  # min_length=2
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_search_rejects_invalid_scope(async_client: AsyncClient, admin_headers):
    """scope غير موجود في Literal → 422."""
    resp = await async_client.post(
        SEARCH_URL,
        headers=admin_headers,
        json={"query": "ما هو ERP؟", "scope": "invalid_scope"},
    )
    assert resp.status_code == 422


# ─── LangGraph Conversational Memory ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_search_with_thread_id_returns_200(async_client: AsyncClient, admin_headers):
    """إرسال thread_id لا يُسبب خطأ ويرجع 200."""
    resp = await async_client.post(
        SEARCH_URL,
        headers=admin_headers,
        json={"query": "ما هو موديول HR؟", "scope": "all", "thread_id": THREAD_A},
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_search_followup_question_returns_200(async_client: AsyncClient, admin_headers):
    """
    السؤال الثاني بنفس thread_id يجب أن يُجيب (مع استيعاب السياق).
    نتحقق فقط من أن النظام لا يرمي error — المحتوى يُختبر يدوياً.
    """
    # السؤال الأول — ينشئ التاريخ في الذاكرة
    await async_client.post(
        SEARCH_URL,
        headers=admin_headers,
        json={"query": "ما هو موديول HR؟", "scope": "all", "thread_id": THREAD_A},
    )

    # السؤال الثاني — متابعة تعتمد على السياق
    resp2 = await async_client.post(
        SEARCH_URL,
        headers=admin_headers,
        json={"query": "وكيف يرتبط بالـ Payroll؟", "scope": "all", "thread_id": THREAD_A},
    )
    assert resp2.status_code == 200
    assert len(resp2.json()["answer"]) > 10


@pytest.mark.asyncio
async def test_different_thread_ids_return_200(async_client: AsyncClient, admin_headers):
    """
    Thread مختلف يبدأ محادثة جديدة منعزلة — لا يتأثر بأي محادثة أخرى.
    """
    resp = await async_client.post(
        SEARCH_URL,
        headers=admin_headers,
        json={"query": "ما هو الـ POS؟", "scope": "all", "thread_id": THREAD_B},
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_search_without_thread_id_is_stateless(async_client: AsyncClient, admin_headers):
    """
    بدون thread_id → يعمل بشكل عادي (Stateless — لا يُحفظ تاريخ).
    """
    resp = await async_client.post(
        SEARCH_URL,
        headers=admin_headers,
        json={"query": "ما هو الـ General Ledger؟", "scope": "all"},
        # لا thread_id
    )
    assert resp.status_code == 200

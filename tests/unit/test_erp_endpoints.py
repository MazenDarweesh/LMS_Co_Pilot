import pytest
from unittest.mock import MagicMock
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport

from src.api.v1.erp import router as erp_router
from src.core.middleware import limiter
from src.models.erp_models import (
    FieldSignatureIn,
    LeftoverRequest,
    NavCandidateIn,
    NavRequest,
)
from src.services.erp_service import erp_service

erp_app = FastAPI()
erp_app.state.limiter = limiter
erp_app.include_router(erp_router)


@pytest.fixture(autouse=True)
def setup_mock_gemini():
    """تهيئة عميل Gemini وهمي لضمان سرعة الاختبارات واستقلاليتها عن الشبكة"""
    mock_client = MagicMock()
    orig = erp_service._gemini_client
    erp_service._gemini_client = mock_client
    yield mock_client
    erp_service._gemini_client = orig


@pytest.fixture
def sample_candidates():
    return [
        NavCandidateIn(id="c1", label="الموردين و المشتريات", path=["الرئيسية", "المشتريات"]),
        NavCandidateIn(id="c2", label="العملاء و المبيعات", path=["الرئيسية", "المبيعات"]),
        NavCandidateIn(id="c3", label="إدارة المخازن والأصناف", path=["الرئيسية", "المخازن"]),
        NavCandidateIn(id="c4", label="الحسابات والقيود اليومية", path=["الرئيسية", "الحسابات"]),
    ]


@pytest.mark.asyncio
async def test_erp_nav_clear_intent_decision_go(sample_candidates):
    """1. طلب واضح ومباشر للمشتريات -> قرار go (ثقة عالية وفارق كافٍ)."""
    req = NavRequest(
        user_message="عايز اسجل فاتورة شراء جديدة من المورد",
        candidates=sample_candidates,
        current_path=["الرئيسية"]
    )
    mock_llm_resp = MagicMock()
    mock_llm_resp.text = (
        '[{"id": "c1", "confidence": 0.92, "reason": "طلب صريح لفاتورة شراء وموردين"},'
        ' {"id": "c2", "confidence": 0.15, "reason": "مبيعات وليست مشتريات"}]'
    )
    erp_service._gemini_client.models.generate_content.return_value = mock_llm_resp

    res = await erp_service.resolve_navigation(req)
    assert res.decision == "go"
    assert len(res.candidates) <= 3
    assert res.candidates[0].id == "c1"
    assert res.candidates[0].confidence >= 0.80


@pytest.mark.asyncio
async def test_erp_nav_ambiguous_intent_decision_ask(sample_candidates):
    """2. طلب غامض بين شاشتين متقاربتين -> قرار ask مع أعلى 3 مرشحين مرتبين تنازلياً."""
    req = NavRequest(
        user_message="عايز افتح الحساب",
        candidates=sample_candidates,
        current_path=[]
    )
    mock_llm_resp = MagicMock()
    mock_llm_resp.text = (
        '[{"id": "c4", "confidence": 0.75, "reason": "حسابات عامة"},'
        ' {"id": "c2", "confidence": 0.65, "reason": "حسابات عملاء"},'
        ' {"id": "c1", "confidence": 0.60, "reason": "حسابات موردين"}]'
    )
    erp_service._gemini_client.models.generate_content.return_value = mock_llm_resp

    res = await erp_service.resolve_navigation(req)
    assert res.decision == "ask"
    assert len(res.candidates) <= 3
    assert res.candidates[0].confidence >= res.candidates[1].confidence


@pytest.mark.asyncio
async def test_erp_nav_gibberish_decision_clarify(sample_candidates):
    """3. نص هراء أو غير ذي صلة -> قرار clarify (الثقة أقل من 0.30)."""
    req = NavRequest(
        user_message="سشيبسي بلابلابلا شششش",
        candidates=sample_candidates,
        current_path=[]
    )
    mock_llm_resp = MagicMock()
    mock_llm_resp.text = (
        '[{"id": "c1", "confidence": 0.10, "reason": "لا يوجد معنى"},'
        ' {"id": "c2", "confidence": 0.05, "reason": "لا يوجد معنى"}]'
    )
    erp_service._gemini_client.models.generate_content.return_value = mock_llm_resp

    res = await erp_service.resolve_navigation(req)
    assert res.decision == "clarify"


@pytest.mark.asyncio
async def test_erp_nav_ignore_hallucinated_ids(sample_candidates):
    """4. الموديل يرجع id غير موجود في المرشحات -> يتم تجاهله تماماً."""
    req = NavRequest(
        user_message="فاتورة مورد",
        candidates=sample_candidates,
        current_path=[]
    )
    mock_llm_resp = MagicMock()
    mock_llm_resp.text = (
        '[{"id": "fake_screen_99", "confidence": 0.99, "reason": "شاشة وهمية"},'
        ' {"id": "c1", "confidence": 0.85, "reason": "شاشة حقيقية"}]'
    )
    erp_service._gemini_client.models.generate_content.return_value = mock_llm_resp

    res = await erp_service.resolve_navigation(req)
    ids = [c.id for c in res.candidates]
    assert "fake_screen_99" not in ids
    assert "c1" in ids


@pytest.mark.asyncio
async def test_erp_nav_llm_failure_lexical_fallback(sample_candidates):
    """5. فشل أو timeout في الـ LLM -> fallback سلس للـ lexical scoring بدون إرجاع 500."""
    req = NavRequest(
        user_message="الموردين و المشتريات",
        candidates=sample_candidates,
        current_path=[]
    )
    erp_service._gemini_client.models.generate_content.side_effect = Exception("API Timeout")

    res = await erp_service.resolve_navigation(req)
    assert isinstance(res.decision, str)
    assert len(res.candidates) > 0
    assert res.candidates[0].id == "c1"
    assert res.candidates[0].confidence > 0.0


@pytest.mark.asyncio
async def test_erp_leftover_missing_option_goes_to_ask_user():
    """6. حقل فيه خيارات options لكن القيمة المستخرجة غير موجودة بالخيارات -> يُحال لـ ask_user."""
    req = LeftoverRequest(
        user_message="الدفع بالفيزا",
        extracted_data={"payment_method": "فيزا إلكترونية", "notes": "عاجل"},
        filled={},
        new_fields=[
            FieldSignatureIn(
                key="payment_method",
                label="طريقة الدفع",
                kind="ng-select",
                disabled=False,
                options=["نقدي", "آجل", "شيك"]  # الفيزا ليست ضمن الخيارات
            ),
            FieldSignatureIn(
                key="notes",
                label="ملاحظات",
                kind="text",
                disabled=False
            )
        ]
    )
    res = await erp_service.resolve_leftover(req)
    assert "payment_method" in res.ask_user
    assert "payment_method" not in res.fields
    assert res.fields.get("notes") == "عاجل"


@pytest.mark.asyncio
async def test_erp_leftover_disabled_fields_are_ignored():
    """7. الحقول المعطلة disabled -> يتم تجاهلها تماماً ولا تملأ ولا تضاف لـ ask_user."""
    req = LeftoverRequest(
        user_message="سجل تاريخ اليوم",
        extracted_data={"doc_date": "2026-10-11", "status": "مسودة"},
        filled={},
        new_fields=[
            FieldSignatureIn(
                key="doc_date",
                label="تاريخ المستند",
                disabled=True  # معطل
            ),
            FieldSignatureIn(
                key="status",
                label="الحالة",
                disabled=True  # معطل
            )
        ]
    )
    res = await erp_service.resolve_leftover(req)
    assert res.fields == {}
    assert res.ask_user == []


@pytest.mark.asyncio
async def test_erp_endpoints_validation_limits_422():
    """8. تجاوز الحدود (candidates > 60 أو user_message > 500) -> 422 Unprocessable Entity."""
    async with AsyncClient(transport=ASGITransport(app=erp_app), base_url="http://test") as client:
        # اختبار تجاوز طول الرسالة > 500 حرف
        too_long_msg = "أ" * 501
        res1 = await client.post(
            "/v1/erp/navigation/resolve",
            json={
                "user_message": too_long_msg,
                "candidates": [{"id": "1", "label": "شاشة", "path": []}],
                "current_path": []
            }
        )
        assert res1.status_code == 422

        # اختبار تجاوز عدد المرشحين > 1200
        too_many_candidates = [
            {"id": f"c_{i}", "label": f"شاشة {i}", "path": []}
            for i in range(1201)
        ]
        res2 = await client.post(
            "/v1/erp/navigation/resolve",
            json={
                "user_message": "فاتورة",
                "candidates": too_many_candidates,
                "current_path": []
            }
        )
        assert res2.status_code == 422

        # اختبار تجاوز new_fields > 40 في leftover
        too_many_fields = [
            {"key": f"k_{i}", "label": f"حقل {i}", "kind": "text", "disabled": False}
            for i in range(41)
        ]
        res3 = await client.post(
            "/v1/erp/form-fill/resolve-leftover",
            json={
                "user_message": "تعديل",
                "extracted_data": {},
                "filled": {},
                "new_fields": too_many_fields
            }
        )
        assert res3.status_code == 422

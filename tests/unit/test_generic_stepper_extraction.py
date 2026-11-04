import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from src.services.erp_copilot import AgenticStepperService


@pytest.mark.asyncio
async def test_resolve_target_screen_report_demotion():
    """التحقق من أن الهدف التنفيذي يستبعد شاشات التقارير ويختار شاشة المعاملة الفعلية"""
    stepper = AgenticStepperService()

    mock_screens = [
        {"page_id": 352, "screen_key": "PurchasesReturnsReport", "name_ar": "تقرير مرتجعات المشتريات", "module": "المشتريات"},
        {"page_id": 291, "screen_key": "PurchasesSettings", "name_ar": "اعدادات المشتريات", "module": "المشتريات"},
        {"page_id": 289, "screen_key": "Purchases", "name_ar": "المشتريات", "module": "المشتريات"},
    ]

    target = await stepper.resolve_target_screen("سجل فاتورة مشتريات للمورد حسين", mock_screens)
    assert target is not None
    assert target["page_id"] == 289
    assert target["name_ar"] == "المشتريات"


@pytest.mark.asyncio
async def test_resolve_target_screen_qualifiers_boosting():
    """التحقق من تفوق الشاشات المحددة بناءً على الكلمات المميزة (مقاولين vs عملاء vs سلف)"""
    stepper = AgenticStepperService()

    mock_screens = [
        {"page_id": 7090, "screen_key": "ContractorExtractions", "name_ar": "اعتماد المستخلصات مقاولين", "module": "المقاولات"},
        {"page_id": 7156, "screen_key": "ClientExtractions", "name_ar": "اعتماد مستخلصات عملاء", "module": "المقاولات"},
        {"page_id": 7158, "screen_key": "Loans", "name_ar": "طلب سلفة", "module": "الموارد البشرية"},
    ]

    # 1. مستخلص مقاول
    target_contractor = await stepper.resolve_target_screen("اعتماد مستخلص مقاولين", mock_screens)
    assert target_contractor is not None
    assert target_contractor["page_id"] == 7090

    # 2. مستخلص عميل
    target_client = await stepper.resolve_target_screen("اعتماد مستخلص عملاء", mock_screens)
    assert target_client is not None
    assert target_client["page_id"] == 7156

    # 3. سلفة
    target_loan = await stepper.resolve_target_screen("عايز اقدم طلب سلفة لموظف", mock_screens)
    assert target_loan is not None
    assert target_loan["page_id"] == 7158


@pytest.mark.asyncio
async def test_generic_extract_transaction_prompt_loan():
    """التحقق من استخراج بيانات نموذج السلف كشاشة مسطحة بمفاتيح EmpId و Amount و Months"""
    stepper = AgenticStepperService()

    fake_response = MagicMock()
    fake_response.text = '{"header": {"EmpId": "محمود السيد", "Amount": 5000, "Months": 6}, "items": [], "target_page_id": 7158, "document_title": "طلب سلفة"}'

    with patch("src.services.erp_copilot.vision_grounding_service.vision_grounding_service._client") as mock_client:
        mock_client.models.generate_content.return_value = fake_response

        res = await stepper.extract_transaction_payload(
            goal="سجل طلب سلفة للموظف محمود السيد بقيمة 5000 جنيه على 6 أشهر",
            target_page_id=7158
        )

        assert res["target_page_id"] == 7158
        assert res["header"]["EmpId"] == "محمود السيد"
        assert res["header"]["Amount"] == 5000
        assert res["header"]["Months"] == 6
        assert len(res["items"]) == 0

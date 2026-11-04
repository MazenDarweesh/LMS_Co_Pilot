import pytest
from src.services.erp_copilot import FormsCatalogService, forms_catalog_service


def test_forms_catalog_loading():
    """التحقق من تحميل كتالوج النماذج وتوفر الشاشات الأساسية الخمس"""
    forms = forms_catalog_service.list_all_forms()
    assert len(forms) >= 5
    page_ids = {f["page_id"] for f in forms}
    assert {289, 290, 7158, 311, 112}.issubset(page_ids)


def test_o1_dictionary_lookups():
    """التحقق من عمل الفهرسة المباشرة O(1) بالقيمة الرقمية والاسم الكودي"""
    # 1. المشتريات
    p289 = forms_catalog_service.get_form_by_page_id(289)
    assert p289 is not None
    assert p289["screen_key"] == "Purchases"
    assert p289["is_excel"] is True
    assert "VendorID" in p289["header_fields"]
    assert "product" in p289["grid_fields"]

    # 2. السلف
    p7158 = forms_catalog_service.get_form_by_screen_key("loans")
    assert p7158 is not None
    assert p7158["page_id"] == 7158
    assert p7158["is_excel"] is False
    assert "EmpId" in p7158["header_fields"]
    assert "Amount" in p7158["header_fields"]
    assert "Months" in p7158["header_fields"]


def test_instant_intent_resolution():
    """التحقق من حل النية في O(1) من نصوص المستخدم الشائعة"""
    res_purchases = forms_catalog_service.resolve_form_by_text("سجل فاتورة مشتريات لمورد")
    assert res_purchases is not None
    assert res_purchases["page_id"] == 289

    res_loan = forms_catalog_service.resolve_form_by_text("عايز اعمل طلب سلفة لموظف")
    assert res_loan is not None
    assert res_loan["page_id"] == 7158

    res_journal = forms_catalog_service.resolve_form_by_text("تسجيل قيد يومية عام")
    assert res_journal is not None
    assert res_journal["page_id"] == 311

    res_store = forms_catalog_service.resolve_form_by_text("اذن صرف مخزني لخامات")
    assert res_store is not None
    assert res_store["page_id"] == 112


def test_prompt_schema_generation():
    """التحقق من توليد مخطط الحقول المخصص لـ Gemini"""
    schema_loan = forms_catalog_service.get_prompt_schema_for_gemini(7158)
    assert schema_loan["page_id"] == 7158
    assert schema_loan["is_excel"] is False
    assert "EmpId" in schema_loan["expected_header"]
    assert "Amount" in schema_loan["expected_header"]
    assert len(schema_loan["expected_grid"]) == 0

    schema_purchases = forms_catalog_service.get_prompt_schema_for_gemini(289)
    assert schema_purchases["page_id"] == 289
    assert schema_purchases["is_excel"] is True
    assert "VendorID" in schema_purchases["expected_header"]
    assert "product" in schema_purchases["expected_grid"]


def test_dynamic_scaling_and_fallback():
    """التحقق من التوسع الديناميكي اللحظي لأي شاشة غير مسجلة في الكتالوج"""
    # 1. شاشة غير مسجلة مع fallback_meta
    fallback = {
        "screen_key": "CustomExtractions",
        "name_ar": "اعتماد مستخلصات خاصة",
        "description": "شاشة فاتورة وجدول مستخلصات مقاولين",
    }
    dynamic_schema = forms_catalog_service.get_prompt_schema_for_gemini(9999, fallback_meta=fallback)
    assert dynamic_schema["page_id"] == 9999
    assert dynamic_schema["is_dynamic"] is True
    assert "EntityName" in dynamic_schema["expected_header"]
    assert "ItemName" in dynamic_schema["expected_grid"]

    # 2. تسجيل ديناميكي أثناء التشغيل (Runtime Registration)
    new_form = {
        "page_id": 8888,
        "screen_key": "NewTestScreen",
        "name_ar": "شاشة اختبار ديناميكية",
        "is_excel": False,
        "header_fields": {
            "CustomField": {
                "label_ar": "حقل مخصص",
                "control_type": "input",
                "is_required": True,
            }
        },
        "grid_fields": {},
    }
    forms_catalog_service.register_dynamic_form(new_form, persist=False)
    retrieved = forms_catalog_service.get_form_by_page_id(8888)
    assert retrieved is not None
    assert retrieved["name_ar"] == "شاشة اختبار ديناميكية"
    assert "CustomField" in retrieved["header_fields"]


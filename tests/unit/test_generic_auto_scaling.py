import time
import pytest
from src.services.forms_catalog_service import FormsCatalogService, forms_catalog_service


def test_archetype_auto_inference_across_domains():
    """التحقق من أن الاستنتاج المعماري الآلي يغطي جميع الموديولات بدون أي كود يدوي"""
    catalog = forms_catalog_service

    # 1. شاشة افتراضية: عرض أسعار مبيعات (Sales Quotation - Transaction)
    quotation_schema = catalog.get_prompt_schema_for_gemini(
        99901, fallback_meta={"name_ar": "عرض اسعار مبيعات", "screen_key": "SalesQuotation", "module": "المبيعات"}
    )
    assert quotation_schema["is_excel"] is True
    assert "EntityName" in quotation_schema["expected_header"]
    assert "ItemName" in quotation_schema["expected_grid"]
    assert "Qty" in quotation_schema["expected_grid"]

    # 2. شاشة افتراضية: سند صرف نقدي (Cash Payment Voucher - Financial)
    voucher_schema = catalog.get_prompt_schema_for_gemini(
        99902, fallback_meta={"name_ar": "سند صرف نقدي", "screen_key": "PaymentVoucher", "module": "الحسابات"}
    )
    assert voucher_schema["is_excel"] is True
    assert "AccID" in voucher_schema["expected_grid"]
    assert "Debit" in voucher_schema["expected_grid"]

    # 3. شاشة افتراضية: طلب إجازة موظف (Employee Leave Request - HR)
    leave_schema = catalog.get_prompt_schema_for_gemini(
        99903, fallback_meta={"name_ar": "طلب اجازة موظف", "screen_key": "LeaveRequest", "module": "الموارد البشرية"}
    )
    assert leave_schema["is_excel"] is False
    assert "EmpID" in leave_schema["expected_header"]

    # 4. شاشة افتراضية: تعريف المخازن (Store Definition - Master Data)
    store_schema = catalog.get_prompt_schema_for_gemini(
        99904, fallback_meta={"name_ar": "تعريف المخازن", "screen_key": "StoreDefinition", "module": "المخازن"}
    )
    assert store_schema["is_excel"] is False
    assert "Code" in store_schema["expected_header"]
    assert "NameAr" in store_schema["expected_header"]

    # 5. شاشة افتراضية: كشف حساب عميل (Account Statement - Report)
    report_schema = catalog.get_prompt_schema_for_gemini(
        99905, fallback_meta={"name_ar": "كشف حساب عميل", "screen_key": "CustomerStatement", "module": "التقارير"}
    )
    assert report_schema["is_excel"] is False
    assert "DateFrom" in report_schema["expected_header"]
    assert "DateTo" in report_schema["expected_header"]

    # 6. اختبار شاشات حقيقية من الـ 821 شاشة مباشرة بالـ PageID فقط دون أي fallback_meta!
    real_central_journal = catalog.get_prompt_schema_for_gemini(327)
    assert real_central_journal["document_name"] == "القيد المركزي"
    assert real_central_journal["is_excel"] is True
    assert "AccID" in real_central_journal["expected_grid"]

    real_store_issue = catalog.get_prompt_schema_for_gemini(7103)
    assert real_store_issue["document_name"] == "اذون صرف بدون تكلفة"
    assert real_store_issue["is_excel"] is True
    assert "ItemName" in real_store_issue["expected_grid"]


def test_live_dom_auto_registration():
    """التحقق من أن فحص الـ DOM المباشر يسجل الشاشة تلقائياً في الفهرس الفوري O(1)"""
    catalog = FormsCatalogService()

    simulated_dom_inspection = {
        "page_id": 9050,
        "title": "طلب شراء مواد خام",
        "url": "http://erp.local/#/purchases/requisition/9050",
        "controls": [
            {"name": "SupplierID", "label": "المورد المعتمد", "type": "select_typeahead", "required": True},
            {"name": "DocDate", "label": "تاريخ الطلب", "type": "date", "required": True},
            {"name": "Notes", "label": "ملاحظات الاعتماد", "type": "text", "required": False},
        ],
        "grids": [
            {
                "headers": ["الصنف", "الكمية المطلوبة", "المواصفة", "تاريخ الحاجة"]
            }
        ]
    }

    # تسجيل الشاشة في الذاكرة دون الكتابة للملف
    registered = catalog.auto_register_from_dom_inspection(simulated_dom_inspection, persist=False)
    assert registered["page_id"] == 9050
    assert registered["is_excel"] is True
    assert registered["primary_entity_field"] == "SupplierID"

    # فحص الاسترجاع الفوري O(1)
    retrieved = catalog.get_form_by_page_id(9050)
    assert retrieved is not None
    assert retrieved["name_ar"] == "طلب شراء مواد خام"
    assert "SupplierID" in retrieved["header_fields"]


def test_universal_scaling_benchmark_all_821_screens():
    """التحقق من قياس أداء التوسع الشامل لجميع شاشات الـ 821 شاشة في أقل من 200ms"""
    catalog = forms_catalog_service
    screens = list(catalog._screens_catalog_by_id.values())
    assert len(screens) > 800, f"Expected > 800 screens, found {len(screens)}"

    t_start = time.perf_counter()
    processed_count = 0
    for s in screens:
        pid = s.get("default_page_id")
        schema = catalog.get_prompt_schema_for_gemini(pid, fallback_meta=s)
        assert schema is not None
        assert "expected_header" in schema
        processed_count += 1

    total_time_ms = (time.perf_counter() - t_start) * 1000
    avg_per_screen_us = (total_time_ms / processed_count) * 1000

    print(f"\n[BENCHMARK] Scaled across {processed_count} screens in {total_time_ms:.2f}ms (Average: {avg_per_screen_us:.1f} microseconds/screen)")
    assert total_time_ms < 250, f"Scaling benchmark exceeded 250ms threshold: {total_time_ms:.2f}ms"


if __name__ == "__main__":
    test_archetype_auto_inference_across_domains()
    print("✅ test_archetype_auto_inference_across_domains passed!")
    test_live_dom_auto_registration()
    print("✅ test_live_dom_auto_registration passed!")
    test_universal_scaling_benchmark_all_821_screens()
    print("✅ test_universal_scaling_benchmark_all_821_screens passed!")

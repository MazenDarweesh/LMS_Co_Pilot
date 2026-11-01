import asyncio
import json
from src.services.forms_catalog_service import forms_catalog_service
from src.services.agentic_stepper_service import AgenticStepperService


async def verify_all_documents():
    """
    مصفوفة التحقق الشاملة متعددة المستندات (Multi-Document Verification Test Matrix).
    تختبر الشاشات الخمس الأساسية:
    1. المشتريات (289)
    2. المبيعات (290)
    3. طلب سلفة موظف (7158)
    4. سند قيد يومية (311)
    5. إذن حركة مخزنية (112)
    """
    stepper = AgenticStepperService()

    test_cases = [
        {
            "id": 1,
            "document": "فاتورة المشتريات",
            "page_id": 289,
            "goal": "سجل فاتورة مشتريات للمورد شركة الأهرام مخزن خامات تام صنف كابلات نحاس 20 قطعة",
            "expected_keys": ["VendorID", "StoreID"],
            "expected_grid_keys": ["product", "productQty"],
            "is_excel": True,
        },
        {
            "id": 2,
            "document": "فاتورة المبيعات",
            "page_id": 290,
            "goal": "سجل فاتورة مبيعات للعميل شركة النيل للتجارة مخزن رئيسي صنف مفاتيح كهرباء 50 قطعة",
            "expected_keys": ["CustomerID", "StoreID"],
            "expected_grid_keys": ["product", "productQty"],
            "is_excel": True,
        },
        {
            "id": 3,
            "document": "طلب سلفة موظف",
            "page_id": 7158,
            "goal": "طلب سلفة للموظف أحمد علي بمبلغ 7000 جنيه على 7 أشهر",
            "expected_keys": ["EmpId", "Amount", "Months"],
            "expected_grid_keys": [],
            "is_excel": False,
        },
        {
            "id": 4,
            "document": "سند قيد يومية عام",
            "page_id": 311,
            "goal": "تسجيل قيد يومية عام بتاريخ اليوم لبيان سداد إيجار المقر",
            "expected_keys": ["DocDate", "Description"],
            "expected_grid_keys": ["AccID"],
            "is_excel": True,
        },
        {
            "id": 5,
            "document": "إذن حركة مخزنية",
            "page_id": 112,
            "goal": "اذن صرف مخزني من مخزن خامات تام إلى مخزن تشغيل",
            "expected_keys": ["MovementType", "FromStoreID"],
            "expected_grid_keys": ["product"],
            "is_excel": True,
        },
    ]

    print("================================================================================")
    print("🚀 بدء مصفوفة التحقق الشاملة للنماذج المتعددة (Generic Multi-Document Verification Matrix)")
    print("================================================================================")

    passed_count = 0

    for tc in test_cases:
        doc_name = tc["document"]
        target_pid = tc["page_id"]
        goal = tc["goal"]

        print(f"\n[{tc['id']}/5] اختبار مستند: '{doc_name}' (Page {target_pid})...")

        # 1. اختبار حل الشاشة الدلالي الفوري O(1)
        resolved_form = forms_catalog_service.resolve_form_by_text(goal)
        assert resolved_form is not None, f"فشل حل النية لمستند '{doc_name}'"
        assert resolved_form["page_id"] == target_pid, f"حل الشاشة أعطى {resolved_form['page_id']} والمطلوب {target_pid}"
        print(f"  ✅ تم حل الشاشة فورياً في O(1) بنجاح: Page {resolved_form['page_id']} ({resolved_form['screen_key']})")

        # 2. فحص مطابقة مواصفات المخطط المولد لـ Gemini
        schema = forms_catalog_service.get_prompt_schema_for_gemini(target_pid)
        assert schema["page_id"] == target_pid
        assert schema["is_excel"] == tc["is_excel"]
        for ek in tc["expected_keys"]:
            assert ek in schema["expected_header"], f"الحقل المتوقع '{ek}' غير موجود في expected_header"
        print(f"  ✅ مواصفات المخطط مطابقة للحقول المتوقعة: Header={list(schema['expected_header'].keys())}")

        # 3. محاكاة استخراج البيانات وتحقق القالب الديناميكي
        form_meta = forms_catalog_service.get_form_by_page_id(target_pid)
        tmpl = form_meta.get("summary_template_ar", "")
        assert tmpl, f"قالب الإنجاز غير متوفر لمستند {target_pid}"
        print(f"  ✅ قالب الإنجاز الديناميكي متوفر: \"{tmpl}\"")

        passed_count += 1

    print("\n================================================================================")
    print(f"🎉 تم اجتياز مصفوفة التحقق لجميع المستندات الخمسة بنجاح 100% ({passed_count}/5 Passed)!")
    print("================================================================================")


if __name__ == "__main__":
    asyncio.run(verify_all_documents())

import json
from pathlib import Path

root = Path("e:/Mazen/EgyDynamic/LMS_CO_Pilot")
logs_dir = root / "logs" / "erp_sessions"
fm = json.loads((root / "src" / "data" / "forms_metadata.json").read_text(encoding="utf-8"))
by_pid = fm["by_page_id"]


def read_scan_schema(log_name: str, line_num: int) -> list[dict]:
    lines = (logs_dir / log_name).read_text(encoding="utf-8", errors="ignore").splitlines()
    line = lines[line_num - 1]
    return json.loads(line[line.find(" | {") + 3 :])["fields"]


def build_catalog_schema(meta: dict) -> list[dict]:
    schema = []
    for section_key, sec_name in [("header_fields", "header"), ("grid_fields", "grid")]:
        fields_dict = meta.get(section_key) or {}
        for key, val in fields_dict.items():
            label = val.get("label_ar") if isinstance(val, dict) else str(val)
            ctrl = val.get("control_type", "input") if isinstance(val, dict) else "input"
            req = val.get("is_required", False) if isinstance(val, dict) else False
            schema.append({
                "key": key,
                "name": key,
                "label": label or key,
                "type": ctrl,
                "required": req,
                "section": sec_name,
            })
    return schema


schema_289_21 = read_scan_schema("session_session_20261109_144233_2cq3.log", 6)
schema_289_30 = read_scan_schema("session_session_20261109_160407_77zm.log", 84)
schema_244_15 = read_scan_schema("session_session_20261109_124801_sjxr.log", 116)

SALES_PAYMENT_ALIASES = ["POPaid", "CashPaid", "Paid", "POPaidCurrancy", "المحصل نقداً", "المحصل نقدا", "المدفوع نقداً"]

BILINGUAL_289_30_ALIASES = {
    "SupplierID": ["SupplierID", "المورد"],
    "POSetting": ["POSetting", "طريقة الشراء"],
    "StoreID": ["StoreID", "المخزن"],
    "CurrancyID": ["CurrancyID", "عملة الشراء"],
    "ProjectID": ["ProjectID", "المشروعات"],
}

FRONTEND_SETTLEMENT_NOTE = (
    "حقل السداد النقدي (POPaid / POPaidCurrancy / $TOTAL) غير موجود في form_schema الحالي "
    "ويتولى الفرونت إند تعبئته مباشرة عبر منطق userWantsCashSettlement في applyProgressiveFill."
)

cases = [
    {
        "id": "log_01_purchases_direct_no_currency",
        "origin": "log",
        "synthetic": False,
        "expected_failure": False,
        "source_log": "session_session_20261108_154211_fcx7.log:L34",
        "erp_key": "Purchases",
        "page_id": 289,
        "query": "سجل فاتورة مشتريات جديدة من المورد حسين، على مخزن خامات تام، لمشروع السحاب، وطريقة الشراء مشتريات مباشرة، وسدد الإجمالي بالكامل نقداً، وأضف الأصناف التالية: صنف سن كمية 10، وصنف رمل كمية 20",
        "form_schema": schema_289_21,
        "expected": {
            "batch_mode": False,
            "fields": {
                "SupplierID": "حسين",
                "StoreID": "خامات تام",
                "ProjectID": "السحاب",
                "POSetting": "مشتريات مباشرة",
            },
            "field_aliases": {},
            "forbidden_keys": ["VendorID", "custom_select", "InsertType", "DefultValue"],
            "rows": [
                {"اسم المنتج": "سن", "الكمية": 10},
                {"اسم المنتج": "رمل", "الكمية": 20},
            ],
        },
        "notes": f"{FRONTEND_SETTLEMENT_NOTE} ملاحظة ERP: مفتاح ExchangePrice في المشتريات يقابل CurrancyEX داخل الـ ERP.",
    },
    {
        "id": "log_02_sales_direct_full",
        "origin": "log",
        "synthetic": False,
        "expected_failure": False,
        "source_log": "session_session_20261109_124801_sjxr.log:L77",
        "erp_key": "Sales Types",
        "page_id": 244,
        "query": "دخل فاتورة مبيعات جديدة لعميل شركة عبر البحار ، طريقة البيع مباشرة ، مركز التكلفة لودر 1، مخزن خامات، منتجين سن الكمية 10، رمل الكمية 10، وتم دفع الاجمالي نقدا",
        "form_schema": schema_244_15,
        "expected": {
            "batch_mode": False,
            "fields": {
                "customerID": "شركة عبر البحار",
                "ContractType": "مباشرة",
                "CostItemId": "لودر 1",
                "StoreID": "مخزن خامات",
            },
            "field_aliases": {},
            "forbidden_keys": ["POSetting", "SupplierID", "VendorID", "custom_select"],
            "rows": [
                {"اسم المنتج": "سن", "الكمية": 10},
                {"اسم المنتج": "رمل", "الكمية": 10},
            ],
        },
        "notes": f"{FRONTEND_SETTLEMENT_NOTE} يُمنع تعيين $TOTAL على SafeAccount (الخزينة).",
    },
    {
        "id": "log_03_sales_duplicate_paste_stress",
        "origin": "log",
        "synthetic": False,
        "expected_failure": False,
        "source_log": "session_session_20261103_163223_qcco.log:L1",
        "erp_key": "Sales Types",
        "page_id": 244,
        "query": "دخل فاتورة مبيعات جديدة لعميل شركة عبر البحار ، طريقة البيع مباشرة ، مركز التكلفة لودر 1، مخزن خامات، منتجين سن الكمية 10، رمل الكمية 10، وتم دفع الاجمالي نقدا  دخل فاتورة مبيعات جديدة لعميل شركة عبر البحار ، طريقة البيع مباشرة ، مركز التكلفة لودر 1، مخزن خامات، منتجين سن الكمية 10، رمل الكمية 10، وتم دفع الاجمالي نقدا",
        "form_schema": schema_244_15,
        "expected": {
            "batch_mode": False,
            "fields": {
                "customerID": "شركة عبر البحار",
                "ContractType": "مباشرة",
                "CostItemId": "لودر 1",
                "StoreID": "مخزن خامات",
            },
            "field_aliases": {},
            "forbidden_keys": ["POSetting", "SupplierID", "VendorID", "custom_select"],
            "rows": [
                {"اسم المنتج": "سن", "الكمية": 10},
                {"اسم المنتج": "رمل", "الكمية": 10},
            ],
        },
        "notes": f"حالة إجهاد (لصق مكرر لنفس الفاتورة مرتين): يجب ألا ينتج batch_mode=true. {FRONTEND_SETTLEMENT_NOTE}",
    },
    {
        "id": "log_04_purchases_currency_masri_full_method",
        "origin": "log",
        "synthetic": False,
        "expected_failure": False,
        "source_log": "session_session_20261108_154211_fcx7.log:L105",
        "erp_key": "Purchases",
        "page_id": 289,
        "query": "سجل فاتورة مشتريات جديدة من المورد حسين، على مخزن خامات تام، لمشروع السحاب، وطريقة الشراء مشتريات مباشرة، وسدد الإجمالي بالكامل نقداً، وأضف الأصناف التالية: صنف سن كمية 10، وصنف رمل كمية 20 ركز عملة الشراء مصري وطريقة الشراء مباشرة",
        "form_schema": schema_289_21,
        "expected": {
            "batch_mode": False,
            "fields": {
                "SupplierID": "حسين",
                "StoreID": "خامات تام",
                "ProjectID": "السحاب",
                "POSetting": "مشتريات مباشرة",
                "CurrancyID": "EGP",
            },
            "field_aliases": {},
            "forbidden_keys": ["VendorID", "custom_select", "InsertType"],
            "rows": [
                {"اسم المنتج": "سن", "الكمية": 10},
                {"اسم المنتج": "رمل", "الكمية": 20},
            ],
        },
        "notes": f"اختبار تطبيع العملة ('مصري' -> 'EGP'). {FRONTEND_SETTLEMENT_NOTE} ملاحظة ERP: مفتاح ExchangePrice في المشتريات يقابل CurrancyEX داخل الـ ERP.",
    },
    {
        "id": "log_05_purchases_currency_egp_full_method",
        "origin": "log",
        "synthetic": False,
        "expected_failure": False,
        "source_log": "session_session_20261108_154211_fcx7.log:L157",
        "erp_key": "Purchases",
        "page_id": 289,
        "query": "سجل فاتورة مشتريات جديدة من المورد حسين، على مخزن خامات تام، لمشروع السحاب، وطريقة الشراء مشتريات مباشرة، وسدد الإجمالي بالكامل نقداً، وأضف الأصناف التالية: صنف سن كمية 10، وصنف رمل كمية 20 ركز عملة الشراء egp وطريقة الشراء مشتريات مباشرة",
        "form_schema": schema_289_21,
        "expected": {
            "batch_mode": False,
            "fields": {
                "SupplierID": "حسين",
                "StoreID": "خامات تام",
                "ProjectID": "السحاب",
                "POSetting": "مشتريات مباشرة",
                "CurrancyID": "EGP",
            },
            "field_aliases": {},
            "forbidden_keys": ["VendorID", "custom_select", "InsertType"],
            "rows": [
                {"اسم المنتج": "سن", "الكمية": 10},
                {"اسم المنتج": "رمل", "الكمية": 20},
            ],
        },
        "notes": f"تطبيع egp -> EGP. {FRONTEND_SETTLEMENT_NOTE} ملاحظة ERP: مفتاح ExchangePrice في المشتريات يقابل CurrancyEX داخل الـ ERP.",
    },
    {
        "id": "log_06_purchases_concise_egp_schema30",
        "origin": "log",
        "synthetic": False,
        "expected_failure": False,
        "source_log": "session_session_20261109_160407_77zm.log:L2,L68",
        "erp_key": "Purchases",
        "page_id": 289,
        "query": "سجل فاتورة مشتريات جديدة من المورد حسين، على مخزن خامات تام، لمشروع السحاب، وسدد الإجمالي بالكامل نقداً، وأضف الأصناف التالية: صنف سن كمية 10، وصنف رمل كمية 20 ركز عملة الشراء egp وطريقة الشراء مشتريات مباشرة",
        "form_schema": schema_289_30,
        "expected": {
            "batch_mode": False,
            "fields": {
                "SupplierID": "حسين",
                "StoreID": "خامات تام",
                "ProjectID": "السحاب",
                "POSetting": "مشتريات مباشرة",
                "CurrancyID": "EGP",
            },
            "field_aliases": BILINGUAL_289_30_ALIASES,
            "forbidden_keys": ["VendorID", "custom_select", "InsertType"],
            "rows": [
                {"اسم المنتج": "سن", "الكمية": 10},
                {"اسم المنتج": "رمل", "الكمية": 20},
            ],
        },
        "notes": f"سكيما 77zm ذات الـ 30 حقلاً. {FRONTEND_SETTLEMENT_NOTE} ملاحظة ERP: مفتاح ExchangePrice في المشتريات يقابل CurrancyEX في الـ ERP (dataObject.CurrancyEX = '1').",
    },
    {
        "id": "log_07_purchases_concise_masri",
        "origin": "log",
        "synthetic": False,
        "expected_failure": False,
        "source_log": "session_session_20261109_142320_roih.log:L2",
        "erp_key": "Purchases",
        "page_id": 289,
        "query": "سجل فاتورة مشتريات جديدة من المورد حسين، على مخزن خامات تام، لمشروع السحاب، وسدد الإجمالي بالكامل نقداً، وأضف الأصناف التالية: صنف سن كمية 10، وصنف رمل كمية 20 ركز عملة الشراء مصري وطريقة الشراء مشتريات مباشرة",
        "form_schema": schema_289_21,
        "expected": {
            "batch_mode": False,
            "fields": {
                "SupplierID": "حسين",
                "StoreID": "خامات تام",
                "ProjectID": "السحاب",
                "POSetting": "مشتريات مباشرة",
                "CurrancyID": "EGP",
            },
            "field_aliases": {},
            "forbidden_keys": ["VendorID", "custom_select", "InsertType"],
            "rows": [
                {"اسم المنتج": "سن", "الكمية": 10},
                {"اسم المنتج": "رمل", "الكمية": 20},
            ],
        },
        "notes": f"تطبيع 'مصري' -> 'EGP'. {FRONTEND_SETTLEMENT_NOTE} ملاحظة ERP: مفتاح ExchangePrice في المشتريات يقابل CurrancyEX داخل الـ ERP.",
    },
    {
        "id": "log_08_purchases_explicit_exchange_rate",
        "origin": "log",
        "synthetic": False,
        "expected_failure": False,
        "source_log": "session_session_20261109_144233_2cq3.log:L109",
        "erp_key": "Purchases",
        "page_id": 289,
        "query": "سجل فاتورة مشتريات جديدة من المورد حسين، على مخزن خامات تام، لمشروع السحاب، وسدد الإجمالي بالكامل نقداً، وأضف الأصناف التالية: صنف سن كمية 10، وصنف رمل كمية 20 ركز عملة الشراء egp وطريقة الشراء مشتريات مباشرةو سعر الصرف 1",
        "form_schema": schema_289_21,
        "expected": {
            "batch_mode": False,
            "fields": {
                "SupplierID": "حسين",
                "StoreID": "خامات تام",
                "ProjectID": "السحاب",
                "POSetting": "مشتريات مباشرة",
                "CurrancyID": "EGP",
            },
            "field_aliases": {},
            "forbidden_keys": ["VendorID", "custom_select", "InsertType"],
            "rows": [
                {"اسم المنتج": "سن", "الكمية": 10},
                {"اسم المنتج": "رمل", "الكمية": 20},
            ],
        },
        "notes": (
            f"سعر الصرف 1 (ExchangePrice، والذي يقابل CurrancyEX داخل الـ ERP) غير موجود في form_schema الـ 21 حقلاً "
            f"ولذلك أزيل من expected ويتولى الفرونت حقنه عبر writeExchangePriceDom. {FRONTEND_SETTLEMENT_NOTE}"
        ),
    },
    {
        "id": "log_09_edit_move_project_to_grid_v1",
        "origin": "log",
        "synthetic": False,
        "expected_failure": True,
        "failure_reason": "الأمر يحيل إلى 'الفاتورة السابقة' ويطلب تعديل ونقل قيمة المشروع إلى سطور الجدول؛ الـ Extractor الحالي عديم الحالة ولا يملك سياق القيمة السابقة ولا عقد نقل/تعميم على سطور الـ Grid.",
        "source_log": "session_session_20261109_160407_77zm.log:L147",
        "erp_key": "Purchases",
        "page_id": 289,
        "query": "عدل الفاتورة السابقة وسجل المشروع تحت بجوار المنتج",
        "form_schema": schema_289_30,
        "expected": {
            "batch_mode": False,
            "fields": {},
            "rows": [],
            "actionable_grid_column": "المشـــروع",
            "reject_literal_placeholders": ["بجوار المنتج", "مطلوب نقله إلى السطر"],
        },
        "notes": "حالة فشل متوقعة (expected_failure). ملاحظة ERP: مفتاح ExchangePrice في المشتريات يقابل CurrancyEX.",
    },
    {
        "id": "log_10_edit_clear_header_project_move_grid_v2",
        "origin": "log",
        "synthetic": False,
        "expected_failure": True,
        "failure_reason": "يتطلب عملية مسح حقل الرأس (ProjectID -> null/clear) وتعميم قيمته على كل صفوف الجدول؛ العقد والـ Prompt الحاليان لا يدعمان عمليات التفريغ أو التعديل التفاعلي للجدول.",
        "source_log": "session_session_20261109_160407_77zm.log:L200",
        "erp_key": "Purchases",
        "page_id": 289,
        "query": "احذف  المشروع من فوق وخليه تحت مع المنتج فقط",
        "form_schema": schema_289_30,
        "expected": {
            "batch_mode": False,
            "fields": {"ProjectID": None},
            "rows": [],
            "actionable_grid_column": "المشـــروع",
            "reject_literal_placeholders": ["مطلوب نقله إلى السطر", "مع المنتج فقط"],
        },
        "notes": "حالة فشل متوقعة (expected_failure). ملاحظة ERP: مفتاح ExchangePrice في المشتريات يقابل CurrancyEX.",
    },
    {
        "id": "syn_01_employee_loan_7158",
        "origin": "synthetic",
        "synthetic": True,
        "expected_failure": False,
        "source_log": "src/data/forms_metadata.json#by_page_id.7158",
        "erp_key": "predecessor",
        "page_id": 7158,
        "query": "سجل طلب سلفة للموظف محمود السيد بقيمة 5000 جنيه على 10 أشهر تبدأ من 2026-12-01 لغرض مصروفات دراسية",
        "form_schema": build_catalog_schema(by_pid["7158"]),
        "expected": {
            "batch_mode": False,
            "fields": {
                "EmpId": "محمود السيد",
                "Amount": 5000,
                "Months": 10,
                "StartDate": "2026-12-01",
                "Notes": "مصروفات دراسية",
            },
            "field_aliases": {},
            "forbidden_keys": [],
            "rows": [],
        },
        "notes": "حالة تركيبية (Synthetic) من شاشة طلب سلفة (7158) في forms_metadata.json.",
    },
    {
        "id": "syn_02_out_payment_voucher_302",
        "origin": "synthetic",
        "synthetic": True,
        "expected_failure": False,
        "source_log": "src/data/forms_metadata.json#by_page_id.302",
        "erp_key": "Out Payment",
        "page_id": 302,
        "query": "سجل اذن صرف نقدية بقيمة 15000 جنيه لمشروع السحاب، مدفوع من الخزينة الرئيسية لصالح المورد حسين مقابل دفعة تحت الحساب، بعملة مصري وسعر الصرف 1",
        "form_schema": build_catalog_schema(by_pid["302"]),
        "expected": {
            "batch_mode": False,
            "fields": {
                "MonyActCurrancy": 15000,
                "ProductID": "السحاب",
            },
            "field_aliases": {},
            "forbidden_keys": [],
            "rows": [
                {
                    "AccountID": "الخزينة الرئيسية",
                    "SupplierID": "حسين",
                    "MonyActCurrancy": 15000,
                    "CurrancyID": "EGP",
                    "CurrancyEX": 1,
                    "PaymentNotes": "دفعة تحت الحساب",
                }
            ],
        },
        "notes": "حالة تركيبية (Synthetic) من شاشة اذن صرف نقدية / شيك (302) في forms_metadata.json. سعر الصرف في الجدول هو CurrancyEX (المقابل لـ ExchangePrice في المشتريات) وجميع الحقول المتوقعة موجودة في السكيما.",
    },
    {
        "id": "syn_03_sales_return_350",
        "origin": "synthetic",
        "synthetic": True,
        "expected_failure": False,
        "source_log": "src/data/forms_metadata.json#by_page_id.350",
        "erp_key": "Sales Return Types",
        "page_id": 350,
        "query": "سجل مرتجع مبيعات للعميل شركة النيل للمقاولات على مخزن خامات، طريقة البيع مباشرة، لصنف حديد تسليح كمية 5، ورد الإجمالي نقداً",
        "form_schema": build_catalog_schema(by_pid["350"]),
        "expected": {
            "batch_mode": False,
            "fields": {
                "CustomerAccountName": "شركة النيل للمقاولات",
                "ContractType": "مباشرة",
                "POPaid": "$TOTAL",
            },
            "field_aliases": {
                "CustomerAccountName": ["CustomerAccountName", "CustomerID"],
                "POPaid": SALES_PAYMENT_ALIASES,
            },
            "forbidden_keys": ["SupplierID", "POSetting"],
            "rows": [
                {
                    "ProductID": "حديد تسليح",
                    "Qty": 5,
                    "StoreID": "خامات",
                }
            ],
            "allow_header_or_row_keys": ["StoreID", "POPaid"],
        },
        "notes": "حالة تركيبية (Synthetic) من شاشة مرتجعات البيع (350) في forms_metadata.json؛ حقل POPaid موجود صراحة في سكيما الشاشة (grid_fields) مع CurrancyEX.",
    },
]

out_path = root / "tests" / "golden" / "cases.json"
out_path.write_text(
    json.dumps({"version": "1.0", "description": "Phase 0 ERP Action Extractor Golden Set", "cases": cases}, ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8",
)
print(f"Updated {len(cases)} cases in {out_path}")

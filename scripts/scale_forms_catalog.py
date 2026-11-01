"""
DynamicPro ERP Co-Pilot — Automated Forms Catalog Scaler & Compiler
===================================================================
تقوم هذه الأداة بأتمتة التوسع الكامل لكتالوج النماذج من الشاشات التجريبية الأولى
إلى كافة شاشات نظام DynamicPro ERP الـ 821 شاشة بالكامل، وتوليد الفهارس
السريعة O(1) Dictionary Index ومخططات الذكاء الاصطناعي دون أي تدخل يدوي.

الاستخدام:
    python scripts/scale_forms_catalog.py --dry-run
    python scripts/scale_forms_catalog.py --compile
"""

import argparse
import json
import sys
import time
from pathlib import Path

# Add project root to path
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from src.services.forms_catalog_service import forms_catalog_service


def scale_catalog(compile_to_file: bool = False, output_path: Path = None):
    screens_path = ROOT_DIR / "src" / "data" / "screens_metadata.json"
    forms_path = output_path or (ROOT_DIR / "src" / "data" / "forms_metadata.json")

    if not screens_path.exists():
        print(f"❌ Error: {screens_path} does not exist.")
        return

    with open(screens_path, "r", encoding="utf-8") as f:
        data = json.load(f)
        screens = data.get("screens", [])

    print(f"🔍 Loaded {len(screens)} screens from {screens_path.name}")

    # Load existing verified forms from forms_metadata.json if exists
    existing_forms_by_id = {}
    if forms_path.exists():
        try:
            with open(forms_path, "r", encoding="utf-8") as ff:
                existing_data = json.load(ff)
                # Keep only handcrafted core forms (< 100 entries) as base verified
                all_raw = existing_data.get("by_page_id", {})
                existing_forms_by_id = {k: v for k, v in all_raw.items() if not v.get("is_auto_scaled")}
                print(f"📌 Found {len(existing_forms_by_id)} already verified/handcrafted form schemas in catalog.")
        except Exception as e:
            print(f"⚠️ Could not load existing forms: {e}")

    by_page_id = dict(existing_forms_by_id)
    by_screen_key = {}
    by_module = {}
    
    # النوايا الأساسية الموثقة التي تحظى بالأولوية المطلقة
    intents_index = {
        "فاتورة مشتريات": 289,
        "فاتورة المشتريات": 289,
        "فواتير المشتريات": 289,
        "فاتورة شراء": 289,
        "تسجيل مشتريات": 289,
        "فاتورة مبيعات": 290,
        "فاتورة المبيعات": 290,
        "فواتير المبيعات": 290,
        "فاتورة بيع": 290,
        "تسجيل مبيعات": 290,
        "سلفة": 7158,
        "طلب سلفة": 7158,
        "طلب السلفة": 7158,
        "سلفة موظف": 7158,
        "قيد": 311,
        "قيد يومية": 311,
        "قيد عام": 311,
        "القيد العام": 311,
        "تحويل مخزني": 112,
        "مناقلة مخزنية": 112,
        "تحويلات الاصناف": 112,
        "نقل بين المخازن": 112,
        "حركة مخزنية": 112,
        "صرف مخزني": 112,
        "إذن حركة مخزنية": 112,
        "اذن صرف مخزني": 112,
    }

    archetype_counts = {
        "verified_handcrafted": len(existing_forms_by_id),
        "transaction_grid": 0,
        "financial_journal": 0,
        "hr_payroll": 0,
        "report_inquiry": 0,
        "master_data_definition": 0,
    }

    t0 = time.perf_counter()

    for s in screens:
        pid = s.get("default_page_id")
        if not pid:
            continue
        pid_str = str(pid)

        # 1. إذا كانت الشاشة مسجلة مسبقاً يدوياً أو عبر الـ DOM نُبقي عليها دون تغيير (Preserve High Fidelity)
        if pid_str in by_page_id:
            form_entry = by_page_id[pid_str]
        else:
            # 2. وإلا نستنتج النمط المعماري والمخطط آلياً (Automated Archetype Inference)
            inferred = forms_catalog_service.infer_archetype_and_schema(s)
            
            # تصنيف الإحصائيات
            if inferred.get("expected_grid") and "ItemName" in inferred["expected_grid"]:
                archetype_counts["transaction_grid"] += 1
            elif inferred.get("expected_grid") and "AccID" in inferred["expected_grid"]:
                archetype_counts["financial_journal"] += 1
            elif "EmpID" in inferred.get("expected_header", {}):
                archetype_counts["hr_payroll"] += 1
            elif "DateFrom" in inferred.get("expected_header", {}):
                archetype_counts["report_inquiry"] += 1
            else:
                archetype_counts["master_data_definition"] += 1

            # تحويل المخطط المستنتج إلى بنية الكتالوج الموحدة
            form_entry = {
                "page_id": pid,
                "screen_key": s.get("screen_key", f"Screen_{pid}"),
                "name_ar": s.get("name_ar", ""),
                "name_en": s.get("name_en", ""),
                "module": s.get("module", "عام"),
                "is_excel": inferred.get("is_excel", False),
                "primary_entity_field": inferred.get("primary_entity_field", "EntityName"),
                "summary_template_ar": inferred.get("summary_template_ar", f"مستند {s.get('name_ar', '')}"),
                "header_fields": {
                    col: {
                        "label_ar": desc,
                        "control_type": "text" if "تاريخ" not in desc else "date",
                        "is_required": False
                    }
                    for col, desc in inferred.get("expected_header", {}).items()
                },
                "grid_fields": {
                    col: {
                        "label_ar": desc,
                        "control_type": "number" if "كمية" in desc or "مبلغ" in desc or "مدين" in desc or "دائن" in desc else "text",
                        "is_required": False
                    }
                    for col, desc in inferred.get("expected_grid", {}).items()
                },
                "is_auto_scaled": True
            }
            by_page_id[pid_str] = form_entry

        # تحديث فهارس O(1)
        k = (form_entry.get("screen_key") or "").strip().lower()
        if k:
            by_screen_key[k] = int(pid)

        mod = form_entry.get("module") or "عام"
        if mod not in by_module:
            by_module[mod] = []
        if int(pid) not in by_module[mod]:
            by_module[mod].append(int(pid))

        # تضمين نوايا الشاشة في الفهرس المباشر
        for intent in s.get("intents", []):
            clean_intent = intent.strip()
            if clean_intent and clean_intent not in intents_index:
                intents_index[clean_intent] = int(pid)

    duration_ms = (time.perf_counter() - t0) * 1000

    print("\n" + "=" * 60)
    print("🚀 AUTOMATED ERP CATALOG SCALING SUMMARY")
    print("=" * 60)
    print(f"* Total Screens Processed: {len(by_page_id)}")
    print(f"* Verified / Handcrafted Schemas: {archetype_counts['verified_handcrafted']}")
    print(f"* Inferred Transaction Multi-line Grids: {archetype_counts['transaction_grid']}")
    print(f"* Inferred Financial Accounting Journals: {archetype_counts['financial_journal']}")
    print(f"* Inferred HR & Payroll Requests: {archetype_counts['hr_payroll']}")
    print(f"* Inferred Reports & Inquiries: {archetype_counts['report_inquiry']}")
    print(f"* Inferred Master Data & Setup Cards: {archetype_counts['master_data_definition']}")
    print(f"* Modules Indexed: {len(by_module)}")
    print(f"* Instant Intents Indexed: {len(intents_index)}")
    print(f"* Processing Time: {duration_ms:.2f}ms (Speed: {(duration_ms / len(by_page_id)) * 1000:.1f} microseconds/screen)")
    print("=" * 60)

    if compile_to_file:
        compiled_data = {
            "by_page_id": by_page_id,
            "by_screen_key": by_screen_key,
            "by_module": by_module,
            "intents_index": intents_index,
            "_metadata": {
                "total_screens": len(by_page_id),
                "compiled_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "version": "2.0.0-scaled"
            }
        }
        with open(forms_path, "w", encoding="utf-8") as out:
            json.dump(compiled_data, out, ensure_ascii=False, indent=2)
        print(f"✅ Compiled and saved full universal catalog ({len(by_page_id)} screens) to: {forms_path}")
    else:
        print("💡 DRY-RUN complete. Run with '--compile' to persist scaled catalog to forms_metadata.json")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scale ERP Forms Metadata Catalog to all screens automatically.")
    parser.add_argument("--compile", action="store_true", help="Compile and persist scaled catalog to forms_metadata.json")
    parser.add_argument("--dry-run", action="store_true", help="Perform benchmark and dry-run without writing to disk")
    args = parser.parse_args()

    scale_catalog(compile_to_file=args.compile)

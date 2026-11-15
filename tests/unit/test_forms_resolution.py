import json
from pathlib import Path
import pytest
from src.services.erp_copilot import forms_catalog_service
from src.services.erp_copilot.erp_service import (
    CORE_PRIMARY_SCREEN_ALLOWLIST_NORM,
    _is_full_screen_name_in_query,
)
from src.utils.arabic_speech_utils import normalize_arabic_text_leaderboard

def test_sales_invoice_resolution_strict_244():
    """Verify that any sales invoice query resolves strictly to page_id 244 (never 290)."""
    test_queries = [
        "دخل فاتورة مبيعات جديدة لعميل شركة عبر البحار",
        "فاتورة مبيعات",
        "فاتورة المبيعات",
        "فواتير المبيعات",
        "سجل فاتورة بيع",
        "تسجيل مبيعات",
    ]
    for q in test_queries:
        resolved = forms_catalog_service.resolve_form_by_text(q)
        assert resolved is not None, f"Query '{q}' should resolve to a form"
        assert resolved["page_id"] == 244, f"Query '{q}' resolved to {resolved['page_id']} instead of 244"
        assert resolved["screen_key"] == "Sales Types"

def test_warehouse_transfer_resolution_290():
    """Verify that store convert / stock transfer resolves to page_id 290 or 112."""
    resolved = forms_catalog_service.resolve_form_by_text("تحويلات المخازن")
    assert resolved is not None
    # 290 is Store Convert Orders
    assert resolved["page_id"] in (290, 112)
    assert resolved["screen_key"] != "Sales Types"


def test_core_primary_screen_allowlist_matches_screens_metadata():
    """Contract test: every screen name in CORE_PRIMARY_SCREEN_ALLOWLIST_NORM must exist in screens_metadata.json."""
    meta_path = Path(__file__).resolve().parent.parent.parent / "src" / "data" / "screens_metadata.json"
    raw = json.loads(meta_path.read_text(encoding="utf-8"))
    catalog_names_norm = {
        normalize_arabic_text_leaderboard(s.get("name_ar", ""))
        for s in raw.get("screens", [])
        if s.get("name_ar")
    }
    missing = [name for name in CORE_PRIMARY_SCREEN_ALLOWLIST_NORM if name not in catalog_names_norm]
    assert not missing, f"Allowlist contains screen names missing from screens_metadata.json: {missing}"


def test_full_screen_name_matcher_rejects_partial_and_accepts_full():
    """Verify _is_full_screen_name_in_query requires the complete screen name (never partial)."""
    assert _is_full_screen_name_in_query("افتح القيد", "القيد العام") == (False, 0)
    assert _is_full_screen_name_in_query("افتح شاشة الاذون", "اذون صرف") == (False, 0)
    assert _is_full_screen_name_in_query("وديني لشاشة البيانات", "بيانات العملاء") == (False, 0)

    assert _is_full_screen_name_in_query("افتح قيود اليومية", "قيود اليومية") == (True, 2)
    assert _is_full_screen_name_in_query("وديني لاذون الصرف", "اذون صرف") == (True, 2)
    assert _is_full_screen_name_in_query("افتح اذون الاضافة", "اذون اضافة") == (True, 2)
    assert _is_full_screen_name_in_query("عايز افتح القيد العام", "القيد العام") == (True, 2)
    assert _is_full_screen_name_in_query("افتح شاشة المنتجات", "المنتجات") == (True, 1)


def test_purchases_form_289_includes_currency_and_safe_account_in_header_fields():
    """Module 5 contract test: page_id 289 fallback metadata includes CurrancyID and SafeAccounId."""
    form_289 = forms_catalog_service.get_form_by_page_id(289)
    assert form_289 is not None
    header_fields = form_289.get("header_fields", {})
    assert "CurrancyID" in header_fields
    assert header_fields["CurrancyID"]["label_ar"] == "عملة الشراء"
    assert "SafeAccounId" in header_fields
    assert header_fields["SafeAccounId"]["label_ar"] == "الخزينة"



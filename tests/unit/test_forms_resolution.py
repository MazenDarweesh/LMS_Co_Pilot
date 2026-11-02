import pytest
from src.services.forms_catalog_service import forms_catalog_service

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

import pytest
import json
from src.core.prompts import ERP_PAYMENT_RULES, get_erp_form_extraction_prompt
from src.services.erp_copilot import forms_catalog_service


def test_erp_payment_rules_content():
    """Verify payment and cash settlement rules are strictly defined."""
    assert "$TOTAL" in ERP_PAYMENT_RULES
    assert "POPaid" in ERP_PAYMENT_RULES
    assert "SafeAccounId" in ERP_PAYMENT_RULES
    assert "CashPaid" in ERP_PAYMENT_RULES


def test_erp_form_extraction_prompt_incorporates_payment_rules():
    """Verify ERP_FORM_EXTRACTION_PROMPT_TEMPLATE includes ERP_PAYMENT_RULES."""
    prompt = get_erp_form_extraction_prompt("فاتورة بيع وسداد نقدا", "{\"fields\": []}")
    assert "$TOTAL" in prompt
    assert "POPaid" in prompt
    assert "SafeAccounId" in prompt


def test_screen_244_schema_contract():
    """Verify enriched screen 244 schema in forms_metadata contains concrete fields."""
    contract = forms_catalog_service.get_prompt_schema_for_gemini(244)
    assert contract["page_id"] == 244
    assert contract["is_excel"] is True
    
    header = contract.get("expected_header", {})
    assert "customerID" in header
    assert "ContractType" in header
    assert "CostItemId" in header
    assert "StoreID" in header
    assert "POPaid" in header
    assert "المحصل نقدا" in header["POPaid"]
    
    grid = contract.get("expected_grid", {})
    assert "product" in grid
    assert "Qty" in grid

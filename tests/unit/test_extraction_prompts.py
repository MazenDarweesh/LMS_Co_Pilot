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
    """Verify ERP_FORM_EXTRACTION_PROMPT_TEMPLATE includes ERP_PAYMENT_RULES and product prefix guidance."""
    prompt = get_erp_form_extraction_prompt("فاتورة بيع وسداد نقدا", "{\"fields\": []}")
    assert "$TOTAL" in prompt
    assert "POPaid" in prompt
    assert "SafeAccounId" in prompt
    assert "صنف سن" in prompt


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


def test_extraction_schema_includes_wave3_payment_fields():
    """Verify response JSON schema exposes top-level paid_amount and paid_cash."""
    from src.services.cognitive_search.search.erp_action_extractor import (
        build_extraction_response_json_schema,
    )

    schema = build_extraction_response_json_schema()
    props = schema["properties"]
    assert props["paid_amount"] == {"type": ["number", "null"]}
    assert props["paid_cash"] == {"type": "boolean"}
    batch_props = props["batch_items"]["items"]["properties"]
    assert batch_props["paid_amount"] == {"type": ["number", "null"]}
    assert batch_props["paid_cash"] == {"type": "boolean"}


def test_build_form_fill_payload_wave3_payment_cases():
    """Verify explicit paid_amount, cash without amount, credit (none), and invalid/ambiguous guards."""
    from src.services.cognitive_search.search.erp_action_extractor import (
        build_form_fill_payload,
    )

    # 1. Explicit paid amount ("والمدفوع 200")
    explicit = build_form_fill_payload(
        {
            "intent": "new",
            "fields": {"SupplierID": "حسين"},
            "rows": [{"اسم المنتج": "سن", "الكمية": 2, "السعر": 100}],
            "paid_amount": 200,
            "paid_cash": False,
        },
        screen_key="Purchases",
        page_id=289,
    )
    assert explicit is not None
    assert explicit["paid_amount"] == 200
    assert explicit["paid_cash"] is False

    # 2. Cash without explicit amount ("نقداً" / "كاش")
    cash_only = build_form_fill_payload(
        {
            "intent": "new",
            "fields": {"SupplierID": "حسين"},
            "rows": [{"اسم المنتج": "سن", "الكمية": 2, "السعر": 100}],
            "paid_amount": None,
            "paid_cash": True,
        },
        screen_key="Purchases",
        page_id=289,
    )
    assert cash_only is not None
    assert cash_only["paid_amount"] is None
    assert cash_only["paid_cash"] is True

    # 3. Neither mentioned (credit / آجل)
    credit = build_form_fill_payload(
        {
            "intent": "new",
            "fields": {"SupplierID": "حسين"},
            "rows": [{"اسم المنتج": "سن", "الكمية": 2, "السعر": 100}],
        },
        screen_key="Purchases",
        page_id=289,
    )
    assert credit is not None
    assert credit["paid_amount"] is None
    assert credit["paid_cash"] is False

    # 4. Ambiguous / invalid / boolean paid_amount must be sanitized to None (never guessed)
    ambiguous_invalid = build_form_fill_payload(
        {
            "intent": "new",
            "fields": {"SupplierID": "حسين"},
            "rows": [{"اسم المنتج": "سن", "الكمية": 1, "السعر": 200}],
            "paid_amount": True,
            "paid_cash": False,
        },
        screen_key="Purchases",
        page_id=289,
    )
    assert ambiguous_invalid is not None
    assert ambiguous_invalid["paid_amount"] is None
    assert ambiguous_invalid["paid_cash"] is False

    negative_invalid = build_form_fill_payload(
        {
            "intent": "new",
            "fields": {"SupplierID": "حسين"},
            "rows": [],
            "paid_amount": -50,
            "paid_cash": False,
        },
        screen_key="Purchases",
        page_id=289,
    )
    assert negative_invalid is not None
    assert negative_invalid["paid_amount"] is None

"""
Unit tests for the modular agentic_stepper package and backward-compatible facade.
Verifies submodule initialization, legacy imports, Arabic NLP rules, and payload extraction.
"""

from unittest.mock import MagicMock, patch
import pytest

from src.services.erp_copilot.agentic_stepper import (
    AgenticStepperService,
    PayloadExtractor,
    ScreenResolver,
    StepperEngine,
    agentic_stepper_service,
    append_session_event,
)
from src.services.erp_copilot.agentic_stepper.screen_resolver import clean_token, tokenize
from src.services.erp_copilot import (
    AgenticStepperService as LegacyAgenticStepperService,
    agentic_stepper_service as legacy_agentic_stepper_service,
)


def test_facade_submodules_instantiation():
    """Verify that AgenticStepperService initializes all specialized submodules cleanly."""
    service = AgenticStepperService(default_max_steps=20)
    assert isinstance(service.resolver, ScreenResolver)
    assert isinstance(service.extractor, PayloadExtractor)
    assert isinstance(service.engine, StepperEngine)
    assert service.default_max_steps == 20
    assert service.engine.default_max_steps == 20


def test_legacy_import_compatibility():
    """Verify that importing from legacy src.services.agentic_stepper_service works identically."""
    assert legacy_agentic_stepper_service is not None
    assert isinstance(legacy_agentic_stepper_service, LegacyAgenticStepperService)
    assert LegacyAgenticStepperService is AgenticStepperService


def test_arabic_tokenization_and_irregular_plurals():
    """Verify Arabic morphological tokenization and irregular plural resolution."""
    assert "فاتورة" in clean_token("فواتير")
    assert "امر" in clean_token("اوامر")
    assert "قيد" in clean_token("قيود")
    assert "صنف" in clean_token("اصناف")
    assert "عميل" in clean_token("عملاء")
    assert "مورد" in clean_token("موردين")
    assert "مخزن" in clean_token("مخازن")

    tokens = tokenize("سجل فواتير اوامر توريد موردين")
    assert "فاتورة" in tokens
    assert "امر" in tokens
    assert "مورد" in tokens


@pytest.mark.asyncio
async def test_screen_resolver_qualifiers_and_demotion():
    """Verify report demotion penalty and qualifier boosting via both Resolver and Facade."""
    mock_screens = [
        {"page_id": 352, "screen_key": "PurchasesReturnsReport", "name_ar": "تقرير مرتجعات المشتريات", "module": "المشتريات"},
        {"page_id": 291, "screen_key": "PurchasesSettings", "name_ar": "اعدادات المشتريات", "module": "المشتريات"},
        {"page_id": 289, "screen_key": "Purchases", "name_ar": "المشتريات", "module": "المشتريات"},
    ]

    # Testing via resolver directly
    resolver = ScreenResolver()
    target = await resolver.resolve_target_screen("سجل فاتورة مشتريات للمورد حسين", mock_screens)
    assert target is not None
    assert target["page_id"] == 289

    # Testing via Facade delegation
    target_facade = await agentic_stepper_service.resolve_target_screen("سجل فاتورة مشتريات للمورد حسين", mock_screens)
    assert target_facade is not None
    assert target_facade["page_id"] == 289


@pytest.mark.asyncio
async def test_payload_extractor_delegation():
    """Verify payload extraction delegation via both PayloadExtractor and Facade."""
    fake_response = MagicMock()
    fake_response.text = '{"header": {"EmpId": "محمود السيد", "Amount": 5000, "Months": 6}, "items": [], "target_page_id": 7158, "document_title": "طلب سلفة"}'

    with patch("src.services.erp_copilot.vision_grounding_service.vision_grounding_service._client") as mock_client:
        mock_client.models.generate_content.return_value = fake_response

        # Via extractor
        extractor = PayloadExtractor()
        res = await extractor.extract_transaction_payload("سجل سلفة لمحمود 5000", target_page_id=7158)
        assert res["target_page_id"] == 7158
        assert res["header"]["EmpId"] == "محمود السيد"

        # Via Facade
        res_facade = await agentic_stepper_service.extract_transaction_payload("سجل سلفة لمحمود 5000", target_page_id=7158)
        assert res_facade["target_page_id"] == 7158
        assert res_facade["header"]["Amount"] == 5000


def test_session_telemetry_append():
    """Verify session telemetry doesn't crash on None or valid session."""
    append_session_event(None, "INFO", "TEST", "Testing None session")
    append_session_event("unit_test_session", "INFO", "TEST", "Testing valid session", {"key": "value"})

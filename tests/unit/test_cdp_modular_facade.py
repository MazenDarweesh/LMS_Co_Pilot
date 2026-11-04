"""
Unit test for the modular CDP package and CdpAgentService Facade.
Validates zero-breaking-changes, submodule instantiation, and delegation integrity.
"""

import pytest
from src.services.cdp import (
    CdpAgentService,
    CdpConnectionManager,
    CdpErpNavigator,
    CdpFormBridge,
    CdpInputDispatcher,
    CdpVisualGrounding,
    cdp_agent_service,
)
from src.services.cdp_agent_service import (
    CdpAgentService as LegacyCdpAgentService,
    cdp_agent_service as legacy_cdp_agent_service,
)


def test_facade_submodules_instantiation():
    """Verify that CdpAgentService initializes all 5 specialized submodules cleanly."""
    service = CdpAgentService(default_port=9222)
    assert isinstance(service.connection, CdpConnectionManager)
    assert isinstance(service.dispatcher, CdpInputDispatcher)
    assert isinstance(service.visual, CdpVisualGrounding)
    assert isinstance(service.navigator, CdpErpNavigator)
    assert isinstance(service.form, CdpFormBridge)
    assert service.default_port == 9222


def test_legacy_import_compatibility():
    """Verify that importing from legacy src.services.cdp_agent_service works identically."""
    assert legacy_cdp_agent_service is not None
    assert isinstance(legacy_cdp_agent_service, LegacyCdpAgentService)
    assert LegacyCdpAgentService is CdpAgentService


def test_arabic_normalization_delegation():
    """Verify normalize_ar works identically across static and instance methods."""
    test_cases = [
        ("إدارة المشتريات", "اداره المشتريات"),
        ("أوامر الإنتاج", "اوامر الانتاج"),
        ("فواتير  المبيعات", "فواتير المبيعات"),
        ("مستودع الخامات 1", "مستودع الخامات 1"),
    ]
    for raw, expected in test_cases:
        assert CdpAgentService.normalize_ar(raw) == expected
        assert cdp_agent_service.normalize_ar(raw) == expected
        assert CdpVisualGrounding.normalize_ar(raw) == expected


def test_resolve_urls_devtunnel_and_local():
    """Verify connection manager URL resolution handles devtunnels and local IPs."""
    conn = CdpConnectionManager()

    # DevTunnel HTTPS / WSS on 443
    h, w = conn.resolve_urls("ppbpzkns-9222.eun1.devtunnels.ms", 9222)
    assert h == "https://ppbpzkns-9222.eun1.devtunnels.ms"
    assert w == "wss://ppbpzkns-9222.eun1.devtunnels.ms"

    # Direct local IP
    h_local, w_local = conn.resolve_urls("127.0.0.1", 9222)
    assert h_local == "http://127.0.0.1:9222"
    assert w_local == "ws://127.0.0.1:9222"


def test_facade_exposes_all_expected_methods():
    """Verify all 30 public methods exist on the CdpAgentService Facade."""
    expected_methods = [
        "is_cdp_available",
        "ensure_cdp_available",
        "get_active_erp_tab",
        "execute_cdp_command",
        "evaluate_script",
        "click_at",
        "type_text",
        "press_key",
        "normalize_ar",
        "capture_screenshot",
        "get_page_state",
        "get_viewport_metrics",
        "show_click_ripple",
        "get_interactive_elements",
        "wait_for_settle",
        "click_element_or_coordinate",
        "navigate_to_erp_screen",
        "navigate_to_erp_screen_dom_click",
        "get_user_authorized_screens",
        "ensure_erp_form_open",
        "fill_erp_form_bridge",
        "snapshot_form_state",
        "get_active_screen_metadata",
        "inspect_active_page_dom",
        "auto_catalog_active_page",
        "aclose",
    ]
    for method_name in expected_methods:
        assert hasattr(cdp_agent_service, method_name), f"Missing method {method_name} on Facade!"
        assert callable(getattr(cdp_agent_service, method_name)), f"Attribute {method_name} is not callable!"


def test_scripts_exist_and_load():
    """Verify that all external JavaScript script files exist and can be loaded via get_script."""
    from src.services.cdp.script_loader import get_script

    scripts = [
        ("click_ripple.js", {"X": 100, "Y": 200}),
        ("dom_click.js", {"X": 100, "Y": 200}),
        ("dom_scanner.js", {}),
        ("page_state.js", {}),
        ("erp_navigation.js", {"TARGET": "289"}),
        ("dom_navigation.js", {"TARGET": "289"}),
        ("ensure_form_open.js", {"TIMEOUT_MS": 5000}),
        ("form_injector.js", {"PAYLOAD": "{}"}),
        ("form_snapshot.js", {}),
        ("screen_metadata.js", {}),
        ("page_inspection.js", {}),
    ]

    for script_name, params in scripts:
        code = get_script(script_name, **params)
        assert code and len(code) > 20, f"Script {script_name} failed to load or is empty!"
        for key, val in params.items():
            assert f"__{key}__" not in code, f"Script {script_name} still has unreplaced __{key}__!"


"""
Unit tests for Hierarchical Telemetry Stages, Session Telemetry Appending, and Event Parser.
Verifies taxonomy, string inheritance, file persistence, and hierarchical prefix queries.
"""

import time
import pytest
from src.services.erp_copilot.agentic_stepper import (
    TelemetryStage,
    append_session_event,
    read_session_events,
    agentic_stepper_service,
)
from src.services.erp_copilot.agentic_stepper.session_telemetry import ERP_LOGS_DIR


def test_telemetry_stage_taxonomy():
    """Verify all stages follow the [SUBSYSTEM.COMPONENT] taxonomy and string inheritance."""
    # Stepper subsystem
    assert TelemetryStage.STEPPER_ENGINE == "STEPPER.ENGINE"
    assert TelemetryStage.STEPPER_RESOLVER == "STEPPER.RESOLVER"
    assert TelemetryStage.STEPPER_EXTRACTOR == "STEPPER.EXTRACTOR"
    assert TelemetryStage.STEPPER_VERIFY == "STEPPER.VERIFY"

    # CDP subsystem
    assert TelemetryStage.CDP_CONNECT == "CDP.CONNECT"
    assert TelemetryStage.CDP_NAVIGATOR == "CDP.NAVIGATOR"
    assert TelemetryStage.CDP_FORM_BRIDGE == "CDP.FORM_BRIDGE"
    assert TelemetryStage.CDP_VISUAL == "CDP.VISUAL"
    assert TelemetryStage.CDP_DISPATCHER == "CDP.DISPATCHER"

    # Browser subsystem
    assert TelemetryStage.BROWSER_BRIDGE == "BROWSER.BRIDGE"
    assert TelemetryStage.BROWSER_FILL == "BROWSER.FILL"

    # String inheritance allows seamless use in string operations
    assert isinstance(TelemetryStage.STEPPER_ENGINE, str)
    assert TelemetryStage.STEPPER_ENGINE.startswith("STEPPER.")
    assert TelemetryStage.CDP_NAVIGATOR.startswith("CDP.")


def test_append_and_read_session_events():
    """Verify writing events and reading them back with hierarchical filters."""
    session_id = f"test_hierarchical_{int(time.time() * 1000)}"

    # 1. Test None and empty session safety
    append_session_event(None, "INFO", TelemetryStage.STEPPER_ENGINE, "No op")
    append_session_event("", "INFO", TelemetryStage.STEPPER_ENGINE, "No op")
    assert read_session_events("") == []
    assert read_session_events("non_existent_session_999999") == []

    # 2. Append multiple hierarchical events
    append_session_event(
        session_id,
        "INFO",
        TelemetryStage.STEPPER_ENGINE,
        "Goal started",
        {"goal": "Test invoice entry", "max_steps": 15},
    )
    append_session_event(
        session_id,
        "INFO",
        TelemetryStage.STEPPER_RESOLVER,
        "Resolved screen to Sales Invoices",
        {"page_id": 244, "name_ar": "فواتير المبيعات"},
    )
    append_session_event(
        session_id,
        "INFO",
        TelemetryStage.STEPPER_EXTRACTOR,
        "Extracted payload via LLM",
        {"items": [{"product": "سن", "qty": 10}]},
    )
    append_session_event(
        session_id,
        "INFO",
        TelemetryStage.CDP_NAVIGATOR,
        "Navigating to page 244",
        {"page_id": 244},
    )
    append_session_event(
        session_id,
        "WARN",
        TelemetryStage.STEPPER_VERIFY,
        "Navigation verify failed",
        {"target_pid": 244, "tx_arrived": False},
    )
    append_session_event(
        session_id,
        "ERROR",
        TelemetryStage.CDP_NAVIGATOR,
        "Navigation retry exceeded limit",
        {"retries": 4},
    )

    # 3. Read back all events
    all_events = read_session_events(session_id)
    assert len(all_events) == 6
    assert all_events[0]["stage"] == "STEPPER.ENGINE"
    assert all_events[0]["details"]["goal"] == "Test invoice entry"

    # 4. Filter by stage prefix: "STEPPER"
    stepper_events = read_session_events(session_id, stage_prefix="STEPPER")
    assert len(stepper_events) == 4
    for ev in stepper_events:
        assert ev["stage"].startswith("STEPPER.")

    # 5. Filter by stage prefix: "CDP"
    cdp_events = read_session_events(session_id, stage_prefix="CDP")
    assert len(cdp_events) == 2
    for ev in cdp_events:
        assert ev["stage"].startswith("CDP.")

    # 6. Filter by level: "ERROR"
    error_events = read_session_events(session_id, level="ERROR")
    assert len(error_events) == 1
    assert error_events[0]["stage"] == "CDP.NAVIGATOR"
    assert error_events[0]["message"] == "Navigation retry exceeded limit"

    # 7. Filter by level: "WARN"
    warn_events = read_session_events(session_id, level="WARN")
    assert len(warn_events) == 1
    assert warn_events[0]["stage"] == "STEPPER.VERIFY"

    # 8. Test Facade delegation
    facade_events = agentic_stepper_service.read_session_events(session_id, stage_prefix="CDP")
    assert len(facade_events) == 2


def test_trace_id_filtering_jsonl_pipes_redaction_and_dedup():
    """Verify trace_id filtering, pipe/newline preservation, session_ prefix dedup, and redaction."""
    from src.services.erp_copilot.agentic_stepper.session_telemetry import (
        ERP_TEST_LOGS_DIR,
        normalize_session_base_id,
    )

    assert normalize_session_base_id("session_20261116_abc") == "20261116_abc"
    assert normalize_session_base_id("session_session_20261116_abc") == "20261116_abc"

    raw_session = f"session_test_jsonl_{int(time.time() * 1000)}"
    base_id = normalize_session_base_id(raw_session)

    append_session_event(
        raw_session,
        "INFO",
        TelemetryStage.BROWSER_USER_QUERY,
        "Query with | pipe and\nnewline",
        {"token": "secret-jwt-123", "nested": {"password": "pw"}, "query": "فاتورة"},
        trace_id="trc_alpha",
        screen_key="PURCHASES",
    )
    append_session_event(
        raw_session,
        "INFO",
        TelemetryStage.STEPPER_RESOLVER,
        "Different trace event",
        {"page_id": 289},
        trace_id="trc_beta",
    )

    expected_file = ERP_TEST_LOGS_DIR / f"session_{base_id}.jsonl"
    assert expected_file.exists()

    alpha_events = read_session_events(raw_session, trace_id="trc_alpha")
    assert len(alpha_events) == 1
    assert alpha_events[0]["message"] == "Query with | pipe and\nnewline"
    assert alpha_events[0]["trace_id"] == "trc_alpha"
    assert alpha_events[0]["screen_key"] == "PURCHASES"
    assert alpha_events[0]["details"]["token"] == "[REDACTED]"
    assert alpha_events[0]["details"]["nested"]["password"] == "[REDACTED]"
    assert alpha_events[0]["details"]["query"] == "فاتورة"


def test_legacy_log_fallback_reading():
    """Verify read_session_events still parses historical pipe-delimited .log files."""
    from src.services.erp_copilot.agentic_stepper.session_telemetry import ERP_TEST_LOGS_DIR

    legacy_id = f"test_legacy_{int(time.time() * 1000)}"
    ERP_TEST_LOGS_DIR.mkdir(parents=True, exist_ok=True)
    legacy_path = ERP_TEST_LOGS_DIR / f"session_{legacy_id}.log"
    legacy_path.write_text(
        '[2026-11-15T12:01:41.784Z] [INFO] [USER_QUERY] [trc:trc_old] User: "فاتورة" | {"mode": "action"}\n',
        encoding="utf-8",
    )
    try:
        events = read_session_events(legacy_id, trace_id="trc_old")
        assert len(events) == 1
        assert events[0]["stage"] == "USER_QUERY"
        assert events[0]["trace_id"] == "trc_old"
        assert events[0]["details"]["mode"] == "action"
    finally:
        if legacy_path.exists():
            legacy_path.unlink()

"""Offline plumbing & WebSocket v16 regression tests for the Phase 0 Golden Set."""

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from websockets.protocol import State

from src.core.config import settings
from src.services.cognitive_search.search.erp_action_extractor import (
    build_form_fill_payload,
    extract_form_fields_if_needed,
    resolve_and_enrich_erp_action_schema,
)
from src.services.erp_copilot.cdp.connection_manager import CdpConnectionManager

GOLDEN_CASES_PATH = Path(__file__).resolve().parent / "cases.json"


def _load_cases() -> list[dict]:
    data = json.loads(GOLDEN_CASES_PATH.read_text(encoding="utf-8"))
    return data["cases"]


GOLDEN_CASES = _load_cases()


def test_golden_cases_structure_and_inventory() -> None:
    """Verify Phase 0 Golden Set holds the 10 unique log cases + synthetic catalog cases."""
    log_cases = [c for c in GOLDEN_CASES if not c.get("synthetic")]
    synthetic_cases = [c for c in GOLDEN_CASES if c.get("synthetic")]
    expected_failures = [c for c in GOLDEN_CASES if c.get("expected_failure")]

    assert len(log_cases) == 10
    assert len(synthetic_cases) >= 2
    assert len(expected_failures) == 2

    # Ensure StoreID DB fix removed stale "خامات تام" string from Golden Set
    assert "خامات تام" not in json.dumps(GOLDEN_CASES, ensure_ascii=False)

    # Ensure no duplicate queries across log cases
    log_queries = [c["query"] for c in log_cases]
    assert len(log_queries) == len(set(log_queries))

    # Ensure ExchangePrice <-> CurrancyEX mapping is documented on relevant cases
    documented = [
        c for c in GOLDEN_CASES
        if "ExchangePrice" in c.get("notes", "") and "CurrancyEX" in c.get("notes", "")
    ]
    assert len(documented) >= 1

    for case in GOLDEN_CASES:
        assert case["id"]
        assert case["query"]
        assert isinstance(case["form_schema"], list) and len(case["form_schema"]) > 0
        assert "expected" in case
        assert "batch_mode" in case["expected"]


@pytest.mark.asyncio
@pytest.mark.parametrize("case", GOLDEN_CASES, ids=[c["id"] for c in GOLDEN_CASES])
async def test_extractor_pipeline_plumbing_offline(case: dict) -> None:
    """
    Exercise the full Extractor plumbing offline with a fake/catalog form_schema
    and a mocked Gemini client (zero network calls).
    """
    effective_fields, effective_schema, resolved_key, resolved_pid, resolved_doc = (
        resolve_and_enrich_erp_action_schema(
            query=case["query"],
            visible_fields=None,
            form_schema=case["form_schema"],
            erp_key=case["erp_key"],
        )
    )

    assert effective_schema and len(effective_schema) > 0
    assert resolved_pid == case["page_id"] or resolved_key == case["erp_key"]

    expected = case["expected"]
    if case.get("expected_failure"):
        simulated_llm_json = {
            "batch_mode": False,
            "fields": {"ProjectID": "بجوار المنتج"},
            "rows": [],
        }
    else:
        simulated_llm_json = {
            "batch_mode": expected.get("batch_mode", False),
            "fields": expected.get("fields", {}),
            "rows": expected.get("rows", []),
        }

    fake_resp = MagicMock()
    fake_resp.text = json.dumps(simulated_llm_json, ensure_ascii=False)
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = fake_resp

    raw_extracted = await extract_form_fields_if_needed(
        gemini_client=mock_client,
        query=case["query"],
        visible_fields=effective_fields,
        form_schema=effective_schema,
    )

    # Confirm Gemini mock invoked once at temperature=0.0 in JSON mode
    mock_client.models.generate_content.assert_called_once()
    call_kwargs = mock_client.models.generate_content.call_args.kwargs
    assert call_kwargs["model"] == settings.GEMINI_MODEL
    assert case["query"] in call_kwargs["contents"]
    assert call_kwargs["config"].temperature == 0.0
    assert call_kwargs["config"].response_mime_type == "application/json"

    assert raw_extracted == simulated_llm_json

    payload = build_form_fill_payload(
        raw_extracted=raw_extracted,
        screen_key=resolved_key,
        page_id=resolved_pid,
        document_name=resolved_doc,
        schema=effective_schema,
    )

    assert payload is not None
    assert payload["intent"] == "form_fill"
    assert payload["fields"] == simulated_llm_json["fields"]
    assert payload["rows"] == simulated_llm_json["rows"]
    assert payload["batch_mode"] is False


@pytest.mark.asyncio
async def test_cdp_connection_manager_uses_websockets_state_open() -> None:
    """
    Regression test for websockets==16.1.1 where ClientConnection removed `.closed`
    and exposes `.state` (`websockets.protocol.State`).
    """
    mgr = CdpConnectionManager()
    ws_url = "ws://127.0.0.1:9222/devtools/page/test-tab"

    # Mock ClientConnection without `.closed` attribute (matches websockets 16.1.1)
    open_ws = SimpleNamespace(state=State.OPEN)
    assert not hasattr(open_ws, "closed")

    existing_handler = MagicMock()
    existing_handler._ws_connection = open_ws
    existing_handler.close = AsyncMock()
    mgr._pydoll_handlers[ws_url] = existing_handler

    reused = await mgr.get_pydoll_handler(ws_url)
    assert reused is existing_handler
    existing_handler.close.assert_not_called()

    # Transition connection to State.CLOSED -> handler must be closed and replaced
    closed_ws = SimpleNamespace(state=State.CLOSED)
    existing_handler._ws_connection = closed_ws

    replacement = await mgr.get_pydoll_handler(ws_url)
    existing_handler.close.assert_awaited_once()
    assert replacement is not existing_handler
    assert mgr._pydoll_handlers[ws_url] is replacement


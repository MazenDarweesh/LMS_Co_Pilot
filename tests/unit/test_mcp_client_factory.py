"""
Unit tests for `src/services/erp_copilot/mcp/client_factory.py`.
Covers:
- Per-user Streamable HTTP connection config & validation
- Hard exclusion of `commit_entry` and `commit_report_designer` from LLM tools
- Runtime interceptor blocking (`McpBlockedToolError`)
- `read_page` output truncation to `MCP_READ_PAGE_MAX_CHARS`
- Telemetry logging via `session_telemetry.append_session_event` with `trace_id`
  and ZERO token/secret leakage
"""

import time
from unittest.mock import AsyncMock, patch

from langchain_core.messages import ToolMessage
from langchain_core.tools import StructuredTool
from langchain_mcp_adapters.interceptors import MCPToolCallRequest
from mcp.types import CallToolResult, TextContent
import pytest

from src.services.erp_copilot.agentic_stepper.session_telemetry import read_session_events
from src.services.erp_copilot.mcp.client_factory import (
    McpBlockedToolError,
    McpClientFactoryService,
    filter_llm_tools,
    truncate_read_page_output,
)


def _make_dummy_tool(name: str) -> StructuredTool:
    async def _noop(**kwargs):
        return "ok"

    return StructuredTool.from_function(
        coroutine=_noop,
        name=name,
        description=f"Dummy tool {name}",
    )


def test_build_connection_config_and_validation():
    factory = McpClientFactoryService()
    factory.initialize(base_url="https://erp.example.com/mcp", read_page_max_chars=500)

    conn = factory.build_connection_config("user-jwt-token-xyz")
    assert conn["transport"] == "streamable_http"
    assert conn["url"] == "https://erp.example.com/mcp"
    assert conn["headers"] == {"Authorization": "Bearer user-jwt-token-xyz"}

    with pytest.raises(ValueError):
        factory.build_connection_config("   ")

    empty_url_factory = McpClientFactoryService()
    empty_url_factory.initialize(base_url="", read_page_max_chars=500)
    with pytest.raises(ValueError):
        empty_url_factory.build_connection_config("valid-token")


def test_filter_llm_tools_hard_blocks_commit_tools_and_enforces_allowlist():
    tools = [
        _make_dummy_tool("list_pages"),
        _make_dummy_tool("read_page"),
        _make_dummy_tool("run_report"),
        _make_dummy_tool("commit_entry"),
        _make_dummy_tool("commit_report_designer"),
        _make_dummy_tool("delete_tenant"),
    ]

    filtered = filter_llm_tools(tools)
    names = [t.name for t in filtered]
    assert names == ["list_pages", "read_page", "run_report"]
    assert "commit_entry" not in names
    assert "commit_report_designer" not in names
    assert "delete_tenant" not in names

    # Even if a caller explicitly passes commit_entry in allowed_tools, it MUST be excluded
    forced = filter_llm_tools(
        tools,
        allowed_tools=frozenset({"read_page", "commit_entry", "commit_report_designer"}),
    )
    assert [t.name for t in forced] == ["read_page"]


@pytest.mark.asyncio
async def test_get_llm_tools_filters_from_client():
    factory = McpClientFactoryService()
    factory.initialize(base_url="https://erp.example.com/mcp", read_page_max_chars=1000)

    mock_tools = [
        _make_dummy_tool("read_page"),
        _make_dummy_tool("commit_entry"),
        _make_dummy_tool("commit_report_designer"),
    ]

    with patch(
        "src.services.erp_copilot.mcp.client_factory.MultiServerMCPClient.get_tools",
        new=AsyncMock(return_value=mock_tools),
    ):
        llm_tools = await factory.get_llm_tools("secret-user-token-abc")

    assert [t.name for t in llm_tools] == ["read_page"]


def test_truncate_read_page_output_for_str_tool_message_and_call_result():
    long_text = "A" * 250

    truncated_str, did_truncate = truncate_read_page_output(long_text, 100)
    assert did_truncate is True
    assert truncated_str.startswith("A" * 100)
    assert "[TRUNCATED 150 chars]" in truncated_str

    short_str, did_truncate_short = truncate_read_page_output("hello", 100)
    assert did_truncate_short is False
    assert short_str == "hello"

    msg = ToolMessage(content=long_text, tool_call_id="tc-1")
    truncated_msg, did_truncate_msg = truncate_read_page_output(msg, 50)
    assert did_truncate_msg is True
    assert isinstance(truncated_msg, ToolMessage)
    assert truncated_msg.content.startswith("A" * 50)
    assert "[TRUNCATED 200 chars]" in truncated_msg.content

    call_res = CallToolResult(content=[TextContent(type="text", text=long_text)])
    truncated_res, did_truncate_res = truncate_read_page_output(call_res, 80)
    assert did_truncate_res is True
    assert isinstance(truncated_res, CallToolResult)
    assert truncated_res.content[0].text.startswith("A" * 80)
    assert "[TRUNCATED 170 chars]" in truncated_res.content[0].text


@pytest.mark.asyncio
async def test_interceptor_blocks_commit_entry_truncates_read_page_and_logs_without_token_leak():
    factory = McpClientFactoryService()
    factory.initialize(base_url="https://erp.example.com/mcp", read_page_max_chars=40)

    secret_token = "eyJhbGciOiJIUzI1NiJ9.super_secret_user_token_value"
    session_id = f"test_mcp_factory_{int(time.time() * 1000)}"
    trace_id = "trc-mcp-001"

    interceptor = factory.build_tool_interceptor(
        session_id=session_id,
        trace_id=trace_id,
        tenant_id="tenant-1",
        user_id="user-42",
        secret_values=(secret_token,),
    )

    # 1. Blocked tool raises McpBlockedToolError and never invokes handler
    called = False

    async def _should_not_run(req):
        nonlocal called
        called = True
        return "should-not-happen"

    blocked_req = MCPToolCallRequest(
        name="commit_entry",
        args={"invoice_id": 99},
        server_name="erp",
        headers={"Authorization": f"Bearer {secret_token}"},
    )
    with pytest.raises(McpBlockedToolError):
        await interceptor(blocked_req, _should_not_run)
    assert called is False

    # 2. read_page output is truncated to 40 chars
    async def _read_page_handler(req):
        return "X" * 120

    read_req = MCPToolCallRequest(
        name="read_page",
        args={"page_id": 244},
        server_name="erp",
        headers={"Authorization": f"Bearer {secret_token}"},
    )
    output = await interceptor(read_req, _read_page_handler)
    assert output.startswith("X" * 40)
    assert "[TRUNCATED 80 chars]" in output

    # 3. Error containing Bearer token is scrubbed in telemetry
    async def _failing_handler(req):
        raise RuntimeError(f"Upstream 401 for Bearer {secret_token}")

    err_req = MCPToolCallRequest(
        name="list_pages",
        args={},
        server_name="erp",
        headers={"Authorization": f"Bearer {secret_token}"},
    )
    with pytest.raises(RuntimeError):
        await interceptor(err_req, _failing_handler)

    # 4. Verify telemetry events have trace_id and ZERO token leakage
    events = read_session_events(session_id)
    assert len(events) == 3
    for ev in events:
        assert ev.get("trace_id") == trace_id
        assert ev.get("stage") == "MCP.TOOL_CALL"
        serialized = str(ev)
        assert secret_token not in serialized
        assert "Authorization" not in ev.get("details", {})

    assert events[0]["details"]["status"] == "blocked"
    assert events[1]["details"]["status"] == "ok"
    assert events[1]["details"]["truncated"] is True
    assert events[2]["details"]["status"] == "error"
    assert "[REDACTED]" in events[2]["details"]["error"]

"""
Streamable HTTP MCP Client Factory & Security Policy Layer
==========================================================
Builds per-user authenticated `MultiServerMCPClient` instances for the ERP MCP
server using Streamable HTTP transport, while enforcing strict LLM tool safety:

1. Hard-blocks destructive commit tools (`commit_entry`, `commit_report_designer`)
   both during tool discovery (`filter_llm_tools`) and at invocation time
   (interceptor defense-in-depth).
2. Applies a read-only tool allowlist by default (`DEFAULT_READONLY_TOOL_ALLOWLIST`).
3. Truncates oversized `read_page` outputs to `settings.MCP_READ_PAGE_MAX_CHARS`.
4. Logs every MCP tool call via `session_telemetry.append_session_event` with
   `trace_id` and ZERO token/secret leakage.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
import re
import time
from typing import Any

from langchain_core.messages import ToolMessage
from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.interceptors import MCPToolCallRequest
from langchain_mcp_adapters.sessions import StreamableHttpConnection
from mcp.types import CallToolResult, TextContent
import structlog

from src.core.config import settings
from src.services.erp_copilot.agentic_stepper.session_telemetry import append_session_event

logger = structlog.get_logger()

# Hard-blocked mutation tools — NEVER exposed to LLM tool calling under any circumstance.
BLOCKED_MUTATION_TOOLS: frozenset[str] = frozenset(
    {
        "commit_entry",
        "commit_report_designer",
    }
)

# Initial read-only tool allowlist for ERP MCP discovery & reporting.
DEFAULT_READONLY_TOOL_ALLOWLIST: frozenset[str] = frozenset(
    {
        "list_pages",
        "read_page",
        "search_pages",
        "get_page_schema",
        "run_report",
        "get_report_schema",
        "query_entries",
        "get_entry",
    }
)

_BEARER_PATTERN = re.compile(r"(Bearer\s+)[A-Za-z0-9\-._~+/]+=*", re.IGNORECASE)


class McpBlockedToolError(PermissionError):
    """Raised when an attempt is made to invoke a blocked or non-allowlisted MCP tool."""


def _scrub_secrets(text: str, secret_values: Sequence[str] = ()) -> str:
    """Removes Bearer tokens and any explicit secret values from log/error strings."""
    cleaned = _BEARER_PATTERN.sub(r"\1[REDACTED]", text)
    for secret in secret_values:
        if secret and len(secret) >= 4:
            cleaned = cleaned.replace(secret, "[REDACTED]")
    return cleaned


def truncate_read_page_output(result: Any, max_chars: int) -> tuple[Any, bool]:
    """
    Truncates oversized `read_page` tool output to `max_chars`.
    Returns `(possibly_truncated_result, was_truncated)`.
    """
    if max_chars <= 0:
        return result, False

    if isinstance(result, str):
        if len(result) <= max_chars:
            return result, False
        omitted = len(result) - max_chars
        return f"{result[:max_chars]}\n...[TRUNCATED {omitted} chars]", True

    if isinstance(result, ToolMessage):
        if isinstance(result.content, str) and len(result.content) > max_chars:
            omitted = len(result.content) - max_chars
            truncated_msg = result.model_copy(
                update={"content": f"{result.content[:max_chars]}\n...[TRUNCATED {omitted} chars]"}
            )
            return truncated_msg, True
        return result, False

    if isinstance(result, CallToolResult):
        remaining = max_chars
        was_truncated = False
        new_content: list[Any] = []
        for item in result.content:
            if isinstance(item, TextContent):
                text = item.text
                if remaining <= 0:
                    was_truncated = True
                    continue
                if len(text) > remaining:
                    omitted = len(text) - remaining
                    new_content.append(
                        TextContent(
                            type="text",
                            text=f"{text[:remaining]}\n...[TRUNCATED {omitted} chars]",
                        )
                    )
                    remaining = 0
                    was_truncated = True
                else:
                    new_content.append(item)
                    remaining -= len(text)
            else:
                new_content.append(item)
        if was_truncated:
            return (
                CallToolResult(
                    content=new_content,
                    structuredContent=result.structuredContent,
                    isError=result.isError,
                ),
                True,
            )
        return result, False

    return result, False


def filter_llm_tools(
    tools: Sequence[BaseTool],
    *,
    allowed_tools: frozenset[str] | None = None,
) -> list[BaseTool]:
    """
    Filters MCP tools for LLM consumption:
    - Always excludes `BLOCKED_MUTATION_TOOLS` (`commit_entry`, `commit_report_designer`),
      even if explicitly requested in `allowed_tools`.
    - Restricts to `allowed_tools` (defaults to `DEFAULT_READONLY_TOOL_ALLOWLIST`).
    """
    effective_allowlist = (
        DEFAULT_READONLY_TOOL_ALLOWLIST if allowed_tools is None else allowed_tools
    ) - BLOCKED_MUTATION_TOOLS
    return [
        tool
        for tool in tools
        if tool.name not in BLOCKED_MUTATION_TOOLS and tool.name in effective_allowlist
    ]


class McpClientFactoryService:
    """Singleton factory for per-user Streamable HTTP MCP clients and safe LLM toolsets."""

    def __init__(self) -> None:
        self._base_url: str | None = None
        self._read_page_max_chars: int = settings.MCP_READ_PAGE_MAX_CHARS

    def initialize(
        self,
        *,
        base_url: str | None = None,
        read_page_max_chars: int | None = None,
    ) -> None:
        """Called from FastAPI lifespan or tests — never performs network I/O."""
        self._base_url = (settings.MCP_BASE_URL if base_url is None else base_url).strip()
        self._read_page_max_chars = (
            settings.MCP_READ_PAGE_MAX_CHARS
            if read_page_max_chars is None
            else read_page_max_chars
        )
        logger.info(
            "MCP Client Factory service ready ✅",
            has_base_url=bool(self._base_url),
            read_page_max_chars=self._read_page_max_chars,
        )

    def _resolve_base_url(self, base_url: str | None) -> str:
        url = (
            base_url
            if base_url is not None
            else (self._base_url if self._base_url is not None else settings.MCP_BASE_URL)
        ).strip()
        if not url:
            raise ValueError("MCP_BASE_URL must be configured and non-empty.")
        return url

    def _resolve_max_chars(self, max_chars: int | None) -> int:
        if max_chars is not None:
            return max_chars
        return self._read_page_max_chars

    def build_connection_config(
        self,
        access_token: str,
        *,
        base_url: str | None = None,
    ) -> StreamableHttpConnection:
        """Builds a Streamable HTTP connection dict with the user's Bearer token."""
        token = access_token.strip()
        if not token:
            raise ValueError("access_token must be non-empty.")
        url = self._resolve_base_url(base_url)
        return StreamableHttpConnection(
            transport="streamable_http",
            url=url,
            headers={"Authorization": f"Bearer {token}"},
        )

    def build_tool_interceptor(
        self,
        *,
        session_id: str | None = None,
        trace_id: str | None = None,
        tenant_id: str | None = None,
        user_id: str | None = None,
        allowed_tools: frozenset[str] | None = None,
        read_page_max_chars: int | None = None,
        secret_values: Sequence[str] = (),
    ) -> Callable[[MCPToolCallRequest, Callable[[MCPToolCallRequest], Awaitable[Any]]], Awaitable[Any]]:
        """
        Creates a `ToolCallInterceptor` enforcing:
        1. Hard-block on `BLOCKED_MUTATION_TOOLS` + allowlist check.
        2. Truncation of `read_page` outputs to `MCP_READ_PAGE_MAX_CHARS`.
        3. Structured telemetry via `append_session_event` with zero token leakage.
        """
        effective_allowlist = (
            DEFAULT_READONLY_TOOL_ALLOWLIST if allowed_tools is None else allowed_tools
        ) - BLOCKED_MUTATION_TOOLS
        max_chars = self._resolve_max_chars(read_page_max_chars)

        async def _interceptor(
            request: MCPToolCallRequest,
            handler: Callable[[MCPToolCallRequest], Awaitable[Any]],
        ) -> Any:
            started = time.perf_counter()
            tool_name = request.name
            arg_keys = sorted(request.args.keys()) if isinstance(request.args, dict) else []

            if tool_name in BLOCKED_MUTATION_TOOLS or tool_name not in effective_allowlist:
                append_session_event(
                    session_id,
                    "WARNING",
                    "MCP.TOOL_CALL",
                    f"Blocked MCP tool invocation: {tool_name}",
                    {
                        "tool_name": tool_name,
                        "arg_keys": arg_keys,
                        "tenant_id": tenant_id,
                        "user_id": user_id,
                        "status": "blocked",
                    },
                    trace_id=trace_id,
                )
                raise McpBlockedToolError(
                    f"MCP tool '{tool_name}' is blocked by security policy."
                )

            try:
                result = await handler(request)
                truncated = False
                if tool_name == "read_page":
                    result, truncated = truncate_read_page_output(result, max_chars)

                duration_ms = round((time.perf_counter() - started) * 1000, 2)
                append_session_event(
                    session_id,
                    "INFO",
                    "MCP.TOOL_CALL",
                    f"MCP tool completed: {tool_name}",
                    {
                        "tool_name": tool_name,
                        "arg_keys": arg_keys,
                        "tenant_id": tenant_id,
                        "user_id": user_id,
                        "duration_ms": duration_ms,
                        "truncated": truncated,
                        "status": "ok",
                    },
                    trace_id=trace_id,
                )
                return result
            except Exception as exc:
                duration_ms = round((time.perf_counter() - started) * 1000, 2)
                safe_error = _scrub_secrets(str(exc), secret_values)
                append_session_event(
                    session_id,
                    "ERROR",
                    "MCP.TOOL_CALL",
                    f"MCP tool failed: {tool_name}",
                    {
                        "tool_name": tool_name,
                        "arg_keys": arg_keys,
                        "tenant_id": tenant_id,
                        "user_id": user_id,
                        "duration_ms": duration_ms,
                        "status": "error",
                        "error": safe_error,
                    },
                    trace_id=trace_id,
                )
                raise

        return _interceptor

    def create_client(
        self,
        access_token: str,
        *,
        base_url: str | None = None,
        server_name: str = "erp",
        session_id: str | None = None,
        trace_id: str | None = None,
        tenant_id: str | None = None,
        user_id: str | None = None,
        allowed_tools: frozenset[str] | None = None,
        read_page_max_chars: int | None = None,
    ) -> MultiServerMCPClient:
        """Creates a per-user `MultiServerMCPClient` with Streamable HTTP transport."""
        connection = self.build_connection_config(access_token, base_url=base_url)
        interceptor = self.build_tool_interceptor(
            session_id=session_id,
            trace_id=trace_id,
            tenant_id=tenant_id,
            user_id=user_id,
            allowed_tools=allowed_tools,
            read_page_max_chars=read_page_max_chars,
            secret_values=(access_token,),
        )
        return MultiServerMCPClient(
            {server_name: connection},
            tool_interceptors=[interceptor],
        )

    async def get_llm_tools(
        self,
        access_token: str,
        *,
        base_url: str | None = None,
        server_name: str = "erp",
        session_id: str | None = None,
        trace_id: str | None = None,
        tenant_id: str | None = None,
        user_id: str | None = None,
        allowed_tools: frozenset[str] | None = None,
        read_page_max_chars: int | None = None,
    ) -> list[BaseTool]:
        """Fetches tools from the user's MCP client and enforces read-only + blocklist filtering."""
        client = self.create_client(
            access_token,
            base_url=base_url,
            server_name=server_name,
            session_id=session_id,
            trace_id=trace_id,
            tenant_id=tenant_id,
            user_id=user_id,
            allowed_tools=allowed_tools,
            read_page_max_chars=read_page_max_chars,
        )
        raw_tools = await client.get_tools()
        return filter_llm_tools(raw_tools, allowed_tools=allowed_tools)

    async def close(self) -> None:
        pass


# Module-level singleton — initialize() called from lifespan or tests
mcp_client_factory_service = McpClientFactoryService()

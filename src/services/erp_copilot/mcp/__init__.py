"""
ERP Co-Pilot MCP Client & OAuth Foundation Package
===================================================
Provides encrypted per-user OAuth token/PKCE storage and a policy-enforced
Streamable HTTP MCP client factory.
"""

from src.services.erp_copilot.mcp.chat_service import (
    UnifiedChatService,
    unified_chat_service,
)
from src.services.erp_copilot.mcp.client_factory import (
    BLOCKED_MUTATION_TOOLS,
    DEFAULT_READONLY_TOOL_ALLOWLIST,
    McpBlockedToolError,
    McpClientFactoryService,
    filter_llm_tools,
    mcp_client_factory_service,
    truncate_read_page_output,
)
from src.services.erp_copilot.mcp.llm_provider import (
    DEFAULT_ANTHROPIC_MODEL,
    DEFAULT_GROQ_MODEL,
    SUPPORTED_CHAT_PROVIDERS,
    LlmProviderConfigError,
    build_chat_model,
    resolve_chat_provider_and_model,
)
from src.services.erp_copilot.mcp.oauth_store import (
    CREATE_MCP_OAUTH_TABLES_SQL,
    InMemoryMcpOAuthRepository,
    McpEncryptionKeyError,
    McpOAuthIsolationError,
    McpOAuthRepository,
    McpOAuthStoreService,
    McpOAuthTokenRecord,
    McpPkceStateRecord,
    McpTokenDecryptionError,
    PostgresMcpOAuthRepository,
    mcp_oauth_store_service,
)

__all__ = [
    "BLOCKED_MUTATION_TOOLS",
    "CREATE_MCP_OAUTH_TABLES_SQL",
    "DEFAULT_ANTHROPIC_MODEL",
    "DEFAULT_GROQ_MODEL",
    "DEFAULT_READONLY_TOOL_ALLOWLIST",
    "InMemoryMcpOAuthRepository",
    "LlmProviderConfigError",
    "McpBlockedToolError",
    "McpClientFactoryService",
    "McpEncryptionKeyError",
    "McpOAuthIsolationError",
    "McpOAuthRepository",
    "McpOAuthStoreService",
    "McpOAuthTokenRecord",
    "McpPkceStateRecord",
    "McpTokenDecryptionError",
    "PostgresMcpOAuthRepository",
    "SUPPORTED_CHAT_PROVIDERS",
    "UnifiedChatService",
    "build_chat_model",
    "filter_llm_tools",
    "mcp_client_factory_service",
    "mcp_oauth_store_service",
    "resolve_chat_provider_and_model",
    "truncate_read_page_output",
    "unified_chat_service",
]

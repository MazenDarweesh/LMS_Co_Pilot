"""
CDP (Chrome DevTools Protocol) Agent Service.
Facade module maintaining 100% backward-compatibility for all existing consumers.
Internally delegates to the decoupled `src.services.cdp` modular package.
"""

from src.services.cdp import (
    CdpAgentService,
    CdpConnectionManager,
    CdpErpNavigator,
    CdpFormBridge,
    CdpInputDispatcher,
    CdpVisualGrounding,
    cdp_agent_service,
)

__all__ = [
    "CdpAgentService",
    "cdp_agent_service",
    "CdpConnectionManager",
    "CdpInputDispatcher",
    "CdpVisualGrounding",
    "CdpErpNavigator",
    "CdpFormBridge",
]

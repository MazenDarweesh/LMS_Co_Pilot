"""
ERP Co-Pilot Domain Services (Agentic & Cognitive-Oriented Subsystem).
====================================================================
Contains services driving autonomous ERP interactions, form auto-filling,
visual grounding, screen resolution, decision memory caching, CDP browser control,
and agentic stepper execution.

Uses PEP 562 lazy attribute loading (__getattr__) so importing a single lightweight
submodule (e.g. forms_catalog_service) never eagerly loads heavy dependencies
(qdrant_client, pydoll, google.genai) unless actually accessed.
"""

from importlib import import_module
from typing import TYPE_CHECKING, Any

# Lightweight core services imported directly so submodule names (e.g. forms_catalog_service)
# never shadow their identically-named singleton instances in package __dict__.
from src.services.erp_copilot.forms_catalog_service import (
    FormsCatalogService,
    forms_catalog_service,
)
from src.services.erp_copilot.vision_grounding_service import (
    VISION_GROUNDING_SYSTEM_PROMPT,
    VisionGroundingService,
    vision_grounding_service,
)
from src.services.erp_copilot.erp_decision_memory_service import (
    ErpDecisionMemoryService,
    candidate_fingerprint,
    erp_decision_memory_service,
    navigation_fingerprint,
)
from src.services.erp_copilot.erp_service import (
    BILINGUAL_SCREEN_MAP,
    DISQUALIFIED_ACTION_KEYWORDS,
    ErpService,
    _stem_arabic_token,
    erp_service,
)

if TYPE_CHECKING:
    from src.services.erp_copilot.agentic_stepper import (
        ERP_LOGS_DIR,
        SHARED_LOGS_DIR,
        AgenticStepperService,
        PayloadExtractor,
        ScreenResolver,
        StepperEngine,
        TelemetryStage,
        _append_session_event,
        agentic_stepper_service,
        append_session_event,
        read_session_events,
    )
    from src.services.erp_copilot.cdp import (
        CdpAgentService,
        CdpConnectionManager,
        CdpErpNavigator,
        CdpFormBridge,
        CdpInputDispatcher,
        CdpVisualGrounding,
        cdp_agent_service,
    )

_LAZY_IMPORTS: dict[str, tuple[str, str]] = {
    "CdpAgentService": ("src.services.erp_copilot.cdp", "CdpAgentService"),
    "cdp_agent_service": ("src.services.erp_copilot.cdp", "cdp_agent_service"),
    "CdpConnectionManager": ("src.services.erp_copilot.cdp", "CdpConnectionManager"),
    "CdpInputDispatcher": ("src.services.erp_copilot.cdp", "CdpInputDispatcher"),
    "CdpVisualGrounding": ("src.services.erp_copilot.cdp", "CdpVisualGrounding"),
    "CdpErpNavigator": ("src.services.erp_copilot.cdp", "CdpErpNavigator"),
    "CdpFormBridge": ("src.services.erp_copilot.cdp", "CdpFormBridge"),
    "AgenticStepperService": ("src.services.erp_copilot.agentic_stepper", "AgenticStepperService"),
    "agentic_stepper_service": ("src.services.erp_copilot.agentic_stepper", "agentic_stepper_service"),
    "ScreenResolver": ("src.services.erp_copilot.agentic_stepper", "ScreenResolver"),
    "PayloadExtractor": ("src.services.erp_copilot.agentic_stepper", "PayloadExtractor"),
    "StepperEngine": ("src.services.erp_copilot.agentic_stepper", "StepperEngine"),
    "TelemetryStage": ("src.services.erp_copilot.agentic_stepper", "TelemetryStage"),
    "append_session_event": ("src.services.erp_copilot.agentic_stepper", "append_session_event"),
    "_append_session_event": ("src.services.erp_copilot.agentic_stepper", "_append_session_event"),
    "read_session_events": ("src.services.erp_copilot.agentic_stepper", "read_session_events"),
    "ERP_LOGS_DIR": ("src.services.erp_copilot.agentic_stepper", "ERP_LOGS_DIR"),
    "SHARED_LOGS_DIR": ("src.services.erp_copilot.agentic_stepper", "SHARED_LOGS_DIR"),
}


def __getattr__(name: str) -> Any:
    if name in _LAZY_IMPORTS:
        module_path, attr_name = _LAZY_IMPORTS[name]
        module = import_module(module_path)
        val = getattr(module, attr_name)
        globals()[name] = val
        return val
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "FormsCatalogService",
    "forms_catalog_service",
    "VisionGroundingService",
    "vision_grounding_service",
    "VISION_GROUNDING_SYSTEM_PROMPT",
    "ErpDecisionMemoryService",
    "erp_decision_memory_service",
    "candidate_fingerprint",
    "navigation_fingerprint",
    "ErpService",
    "erp_service",
    "_stem_arabic_token",
    "BILINGUAL_SCREEN_MAP",
    "DISQUALIFIED_ACTION_KEYWORDS",
    "CdpAgentService",
    "cdp_agent_service",
    "CdpConnectionManager",
    "CdpInputDispatcher",
    "CdpVisualGrounding",
    "CdpErpNavigator",
    "CdpFormBridge",
    "AgenticStepperService",
    "agentic_stepper_service",
    "ScreenResolver",
    "PayloadExtractor",
    "StepperEngine",
    "TelemetryStage",
    "append_session_event",
    "_append_session_event",
    "read_session_events",
    "ERP_LOGS_DIR",
    "SHARED_LOGS_DIR",
]

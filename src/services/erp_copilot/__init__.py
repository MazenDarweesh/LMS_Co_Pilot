"""
ERP Co-Pilot Domain Services (Agentic & Cognitive-Oriented Subsystem).
====================================================================
Contains services driving autonomous ERP interactions, form auto-filling,
visual grounding, screen resolution, decision memory caching, CDP browser control,
and agentic stepper execution.
"""

from src.services.erp_copilot.forms_catalog_service import (
    FormsCatalogService,
    forms_catalog_service,
)
from src.services.erp_copilot.vision_grounding_service import (
    VisionGroundingService,
    vision_grounding_service,
    VISION_GROUNDING_SYSTEM_PROMPT,
)
from src.services.erp_copilot.erp_decision_memory_service import (
    ErpDecisionMemoryService,
    erp_decision_memory_service,
    candidate_fingerprint,
    navigation_fingerprint,
)
from src.services.erp_copilot.erp_service import (
    ErpService,
    erp_service,
    _stem_arabic_token,
    BILINGUAL_SCREEN_MAP,
    DISQUALIFIED_ACTION_KEYWORDS,
)
from src.services.erp_copilot.cdp import (
    CdpAgentService,
    cdp_agent_service,
    CdpConnectionManager,
    CdpInputDispatcher,
    CdpVisualGrounding,
    CdpErpNavigator,
    CdpFormBridge,
)
from src.services.erp_copilot.agentic_stepper import (
    AgenticStepperService,
    agentic_stepper_service,
    ScreenResolver,
    PayloadExtractor,
    StepperEngine,
    TelemetryStage,
    append_session_event,
    _append_session_event,
    read_session_events,
    ERP_LOGS_DIR,
    SHARED_LOGS_DIR,
)

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

"""
Agentic Stepper Service (Backward-Compatibility Facade Entry Point).
Re-exports the modular AgenticStepperService and subcomponents from src.services.agentic_stepper.
Guarantees 100% Zero Breaking Changes across all existing callers, API endpoints, and tests.
"""

from src.services.agentic_stepper import (
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

__all__ = [
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


"""
Shared Infrastructure Subsystem Package.
Provides cross-cutting authentication (Zero-Hop RBAC, HMAC Webhooks),
feedback storage & analytics, and asynchronous PostgreSQL event logging.
"""

from src.services.shared_infrastructure.auth_service import (
    AuthValidatorService,
    auth_validator_service,
    UserContext,
    _build_user_entities,
    get_current_user,
    get_optional_user,
    get_guest_user_context,
    require_role,
    verify_webhook_signature,
)
from src.services.shared_infrastructure.event_logger import (
    EventLoggerService,
    event_logger_service,
)
from src.services.shared_infrastructure.feedback_service import (
    FeedbackService,
    feedback_service,
)

__all__ = [
    "AuthValidatorService",
    "auth_validator_service",
    "UserContext",
    "_build_user_entities",
    "get_current_user",
    "get_optional_user",
    "get_guest_user_context",
    "require_role",
    "verify_webhook_signature",
    "FeedbackService",
    "feedback_service",
    "EventLoggerService",
    "event_logger_service",
]

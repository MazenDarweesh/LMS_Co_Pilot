"""
LMS Bridge Subsystem Package.
Handles direct communication with the external LMS backend, permission caching,
and lesson-specific content generation (quizzes, summaries).
"""

from src.services.lms_bridge.lesson_content_service import (
    LessonContentService,
    lesson_content_service,
)
from src.services.lms_bridge.lms_client import (
    LMSClientService,
    lms_client_service,
)

__all__ = [
    "LMSClientService",
    "lms_client_service",
    "LessonContentService",
    "lesson_content_service",
]

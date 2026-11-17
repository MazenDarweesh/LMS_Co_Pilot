"""
Pydantic Contracts for Unified General Chat + LMS + ERP Navigation SSE Streaming
================================================================================
Request and history schemas shared by `POST /v1/erp/chat/stream` and
`UnifiedChatService`. Reuses `NavCandidateIn` from `src.models.erp_models` (DRY).
"""

from typing import Any, Literal
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator

from src.models.erp_models import NavCandidateIn


class ChatHistoryMessage(BaseModel):
    """Single conversational turn sent in request history."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    role: Literal["user", "assistant", "system"] = Field(
        ...,
        description="Speaker role: user, assistant, or system",
    )
    content: str = Field(
        ...,
        max_length=16000,
        description="Plain text content of the message",
    )

    @field_validator("role", mode="before")
    @classmethod
    def normalize_role(cls, value: Any) -> str:
        raw = str(value or "").strip().lower()
        if raw in {"human", "user"}:
            return "user"
        if raw in {"assistant", "ai", "bot", "model"}:
            return "assistant"
        if raw == "system":
            return "system"
        return raw


class ErpChatStreamRequest(BaseModel):
    """Request payload for unified general chat SSE streaming (`POST /v1/erp/chat/stream`)."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    query: str = Field(
        ...,
        min_length=1,
        max_length=4000,
        validation_alias=AliasChoices("query", "message", "question", "prompt", "text"),
        description="Current user message or question",
    )
    history: list[ChatHistoryMessage] = Field(
        default_factory=list,
        description="Prior conversational turns (bounded server-side by AGENT_MAX_HISTORY_MESSAGES)",
    )
    thread_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("thread_id", "threadId", "ThreadId"),
        description="Conversation thread identifier",
    )
    erp_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("erp_key", "erpKey", "ErpKey"),
        description="Active ERP screen key if available",
    )
    active_screen_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "active_screen_key",
            "activeScreenKey",
            "screen_key",
            "screenKey",
        ),
        description="Currently open ERP screen key or page name",
    )
    trace_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("trace_id", "traceId", "TraceId"),
        description="Client-generated trace identifier for session black-box telemetry",
    )
    lesson_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("lesson_id", "lessonId", "LessonId"),
        description="Optional single LMS lesson scope filter",
    )
    lesson_ids: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("lesson_ids", "lessonIds", "LessonIds"),
        description="Optional multi-lesson LMS scope filter",
    )
    candidates: list[NavCandidateIn] = Field(
        default_factory=list,
        max_length=1200,
        description="Live ERP navigation candidates scanned from the host UI",
    )

    @field_validator("query", mode="before")
    @classmethod
    def strip_query(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("history", "lesson_ids", "candidates", mode="before")
    @classmethod
    def coerce_none_to_empty_list(cls, value: Any) -> Any:
        if value is None:
            return []
        return value

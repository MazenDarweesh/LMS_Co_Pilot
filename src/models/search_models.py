"""
Search Models — Request/Response schemas for the Hybrid RAG Search endpoint.
=============================================================================
Separated from schemas.py to keep concerns clean (Week 8).
"""

import uuid
from enum import Enum
from typing import Literal
from pydantic import BaseModel, Field, field_validator, ConfigDict, AliasChoices



class SearchRequest(BaseModel):
    """طلب البحث الهجين — يدعم تضييق النطاق (scope) وفلترة المعرّفات متوافقاً مع .NET و Angular."""
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    query: str = Field(
        ...,
        min_length=1,
        validation_alias=AliasChoices("query", "message", "question", "prompt", "text"),
        description="سؤال الطالب"
    )
    scope: str = Field(
        default="all",
        validation_alias=AliasChoices("scope", "Scope"),
        description="نطاق البحث"
    )
    module_id: str | None = Field(default=None, validation_alias=AliasChoices("module_id", "moduleId", "ModuleId"))
    unit_id: str | None = Field(default=None, validation_alias=AliasChoices("unit_id", "unitId", "UnitId"))
    lesson_id: str | None = Field(default=None, validation_alias=AliasChoices("lesson_id", "lessonId", "LessonId"))
    playlist_id: str | None = Field(default=None, validation_alias=AliasChoices("playlist_id", "playlistId", "PlaylistId"))
    video_id: str | None = Field(default=None, validation_alias=AliasChoices("video_id", "videoId", "VideoId"))
    limit: int = Field(default=5, ge=1, le=20, validation_alias=AliasChoices("limit", "Limit"))
    thread_id: str | None = Field(default=None, validation_alias=AliasChoices("thread_id", "threadId", "ThreadId"))

    @field_validator("scope", mode="before")
    @classmethod
    def normalize_scope(cls, v: str | None) -> str:
        if not v:
            return "all"
        v_norm = str(v).strip().lower()
        if v_norm in {"all", "course", "standalone", "playlist", "lesson"}:
            return v_norm
        return "all"

    @field_validator("limit", mode="before")
    @classmethod
    def normalize_limit(cls, v: int | str | None) -> int:
        if v is None or v == "":
            return 5
        try:
            val = int(v)
            return max(1, min(20, val))
        except (ValueError, TypeError):
            return 5


class SourceItem(BaseModel):
    """مصدر واحد في الإجابة — فيديو أو PDF."""
    type: Literal["video", "pdf"]
    url: str | None = None          # يوتيوب مع timestamp
    title: str | None = None        # عنوان توضيحي للمصدر (للعرض المباشر في الواجهة)
    start: int | None = None        # بالثواني
    end: int | None = None
    page: int | None = None         # للـ PDF فقط
    section: str | None = None      # عنوان القسم في PDF
    lesson_id: str | None = None    # معرف الدرس للاستشهاد والتحقق من الصلاحيات


class SearchResponse(BaseModel):
    """الاستجابة النهائية — إجابة مع مصادر واستشهادات."""
    answer: str
    sources: list[SourceItem]
    query_used: str


class FeedbackRating(str, Enum):
    UP = "UP"
    DOWN = "DOWN"


class FeedbackRequest(BaseModel):
    """طلب تسجيل تقييم الطالب للإجابة مع منع التكرار."""
    query: str = Field(..., min_length=2, description="سؤال الطالب الأصلي")
    answer: str = Field(..., min_length=2, description="الإجابة المقدمة من النظام")
    rating: FeedbackRating = Field(..., description="تقييم الطالب: إيجابي UP أو سلبي DOWN")
    comment: str | None = Field(None, max_length=1000, description="ملاحظة الطالب الاختيارية")
    lesson_id: str | None = Field(None, description="معرف الدرس المرتبط")
    thread_id: str | None = Field(None, description="معرف جلسة المحادثة")
    # NOTE: query_hash & answer_hash are computed server-side from content — not accepted from client.
    sources: list[SourceItem] | None = Field(None, description="المصادر والاستشهادات المرتبطة بالإجابة (حد أقصى 5)")

    @field_validator("rating", mode="before")
    @classmethod
    def normalize_rating(cls, v: str | FeedbackRating) -> str | FeedbackRating:
        if isinstance(v, str):
            return v.strip().upper()
        return v


class FeedbackResponse(BaseModel):
    """استجابة تسجيل التقييم."""
    status: Literal["success", "duplicate"] = "success"
    message: str = "شكراً لمشاركتك! تم تسجيل ملاحظاتك للمساعدة في تحسين جودة الإجابات. 🎓"


class FeedbackItemResponse(BaseModel):
    """سجل تقييم واحد في الاستعلامات الإدارية."""
    id: uuid.UUID
    tenant_id: str
    department_id: str | None = None
    user_id: str
    user_role: str = "Student"
    lesson_id: str | None = None
    thread_id: str | None = None
    query_hash: str
    answer_hash: str
    query_text: str
    answer_text: str
    rating: FeedbackRating
    comment: str | None = None
    sources: list[dict] = Field(default_factory=list)
    created_at: str | None = None


class FeedbackAnalyticsResponse(BaseModel):
    """إحصائيات الرضا التجميعية للدرس أو الشركة."""
    total_votes: int
    up_votes: int
    down_votes: int
    satisfaction_rate: float


class AdminFeedbackResponse(BaseModel):
    """استجابة الاستعلام الإداري لتقييمات الطلاب."""
    records: list[FeedbackItemResponse]
    analytics: FeedbackAnalyticsResponse
    limit: int
    offset: int



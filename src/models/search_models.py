"""
Search Models — Request/Response schemas for the Hybrid RAG Search endpoint.
=============================================================================
Separated from schemas.py to keep concerns clean (Week 8).
"""

import uuid
from enum import Enum
from typing import Literal
from pydantic import BaseModel, Field



class SearchRequest(BaseModel):
    """طلب البحث الهجين — يدعم تضييق النطاق (scope) وفلترة المعرّفات."""
    query: str = Field(..., min_length=2, description="سؤال الطالب")
    scope: Literal["all", "course", "standalone", "playlist"] = Field(
        "all", description="نطاق البحث"
    )
    module_id: str | None = None
    unit_id: str | None = None
    lesson_id: str | None = None
    playlist_id: str | None = None
    video_id: str | None = None
    limit: int = Field(5, ge=1, le=10, description="عدد المصادر المطلوبة")
    thread_id: str | None = Field(None, description="معرف جلسة المحادثة (لحفظ السياق)")


class SourceItem(BaseModel):
    """مصدر واحد في الإجابة — فيديو أو PDF."""
    type: Literal["video", "pdf"]
    url: str | None = None          # يوتيوب مع timestamp
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



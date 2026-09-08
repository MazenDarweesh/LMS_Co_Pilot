"""
Search Models — Request/Response schemas for the Hybrid RAG Search endpoint.
=============================================================================
Separated from schemas.py to keep concerns clean (Week 8).
"""

from pydantic import BaseModel, Field
from typing import Literal


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

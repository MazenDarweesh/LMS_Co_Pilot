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
    lesson_ids: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("lesson_ids", "lessonIds", "LessonIds"),
        description="قائمة بمعرفات الدروس للبحث الموجه عبر عدة دروس (Cross-Module Multi-Lesson)"
    )
    playlist_id: str | None = Field(default=None, validation_alias=AliasChoices("playlist_id", "playlistId", "PlaylistId"))
    video_id: str | None = Field(default=None, validation_alias=AliasChoices("video_id", "videoId", "VideoId"))
    level_id: str | None = Field(default=None, validation_alias=AliasChoices("level_id", "levelId", "LevelId"))
    type_id: str | None = Field(default=None, validation_alias=AliasChoices("type_id", "typeId", "TypeId"))
    limit: int = Field(default=5, ge=1, le=20, validation_alias=AliasChoices("limit", "Limit"))
    thread_id: str | None = Field(default=None, validation_alias=AliasChoices("thread_id", "threadId", "ThreadId"))
    skip_cache: bool = Field(
        default=False,
        validation_alias=AliasChoices("skip_cache", "skipCache", "bypass_cache", "bypassCache", "retry", "is_retry"),
        description="تجاوز الكاش لإعادة المحاولة وتوليد إجابة جديدة طازجة"
    )
    visible_fields: list[str] | None = Field(
        default=None,
        validation_alias=AliasChoices("visible_fields", "visibleFields", "VisibleFields"),
        description="قائمة أسماء وخانات الفورم المفتوحة في شاشة الـ ERP"
    )
    form_schema: list[dict] | None = Field(
        default=None,
        validation_alias=AliasChoices("form_schema", "formSchema", "FormSchema"),
        description="مخطط حقول وخانات وجداول شاشة الـ ERP التفصيلي"
    )
    erp_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("erp_key", "erpKey", "ErpKey", "screen_key", "screenKey"),
        description="كود شاشة الـ ERP الحالية"
    )
    erp_intent: str | None = Field(
        default=None,
        validation_alias=AliasChoices("erp_intent", "erpIntent", "ErpIntent"),
        description="نية المستخدم كما حددها موجّه الذكاء الاصطناعي (question / navigate / action)"
    )

    @property
    def scope_fingerprint(self) -> str:
        """بصمة رقمية للنطاق والفلاتر لعزل الكاش ومنع تداخل نتائج نطاقات مختلفة بما في ذلك الدروس المتعددة."""
        scope_val = self.scope or "all"
        effective_mod = self.module_id or "" if scope_val == "module" else ""
        effective_unit = self.unit_id or "" if scope_val == "unit" else ""
        
        if self.lesson_ids:
            effective_lesson = ",".join(sorted(self.lesson_ids))
        elif scope_val == "lesson":
            effective_lesson = self.lesson_id or ""
        else:
            effective_lesson = ""

        # In non-standard or legacy scopes, preserve whichever IDs are provided
        if scope_val not in {"all", "module", "unit", "lesson", "lessons", "multi_lesson"}:
            effective_mod = self.module_id or ""
            effective_unit = self.unit_id or ""
            effective_lesson = ",".join(sorted(self.lesson_ids)) if self.lesson_ids else (self.lesson_id or "")

        parts = [
            scope_val,
            effective_mod,
            effective_unit,
            effective_lesson,
            self.level_id or "",
            self.type_id or "",
            self.playlist_id or "",
            self.video_id or "",
            self.erp_key or "",
        ]
        return ":".join(parts)

    @field_validator("scope", mode="before")
    @classmethod
    def normalize_scope(cls, v: str | None) -> str:
        if not v:
            return "all"
        v_norm = str(v).strip().lower()
        if v_norm in {"all", "module", "unit", "lesson", "lessons", "multi_lesson", "course", "standalone", "playlist"}:
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
    """الاستجابة النهائية — إجابة مع مصادر واستشهادات ومصدر الرد."""
    answer: str
    sources: list[SourceItem]
    query_used: str
    provenance: str = Field(default="RAG_GENERATION", description="مصدر الإجابة: EXACT_CACHE | SEMANTIC_CACHE | INTENT_ROUTER | RAG_GENERATION")
    cache_hit: bool = Field(default=False, description="هل تم الرد من الكاش؟")
    latency_ms: float | None = Field(default=None, description="زمن الاستجابة بالمللي ثانية")


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



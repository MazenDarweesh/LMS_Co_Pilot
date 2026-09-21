import re
import hashlib
from datetime import datetime, timezone
from pydantic import BaseModel, Field, field_validator, model_validator, computed_field, AliasChoices, ConfigDict
from typing import Self

from src.models.entities import ContentType, SourceType

YOUTUBE_REGEX = re.compile(r"(?:v=|\/)([a-zA-Z0-9_-]{11})")


def extract_video_id(url: str) -> str:
    """
    استخراج معرف الفيديو الموحد من رابط يوتيوب أو توليد بصمة حتمية (Deterministic Hash) للروابط الأخرى.
    يضمن هذا التوحيد إمكانية إعادة استخدام مقاطع الفيديو عبر عدة موديولات ودروس.
    """
    if not url:
        return ""
    match = YOUTUBE_REGEX.search(url)
    if match:
        return match.group(1)
    return hashlib.sha256(url.strip().encode("utf-8")).hexdigest()[:16]

class AudioIngestRequest(BaseModel):
    youtube_url: str = Field(..., description="رابط يوتيوب الخاص بالمحاضرة")
    lesson_id: str = Field(..., description="المعرف الفريد للدرس (سيعمل كـ session_id للمتابعة)")

class AudioTranscriptionRequest(BaseModel):
    file_path: str = Field(..., description="المسار المحلي لملف الصوت")

class AudioTranscriptionResponse(BaseModel):
    text: str = Field(..., description="النص المفرغ")
    duration: float = Field(..., description="مدة الملف بالثواني")

class RAGQueryRequest(BaseModel):
    query: str = Field(..., description="سؤال المستخدم للـ RAG")
    limit: int = Field(5, description="عدد النتائج المسترجعة")

class RAGQueryResponse(BaseModel):
    answer: str = Field(..., description="الإجابة المعززة بالـ AI")
    sources: list[str] = Field(..., description="المصادر المستخدمة")

# Schema مخصص فقط لرد الذكاء الاصطناعي (أسرع وأوفر للـ Tokens)
class LLMNormalizationResponse(BaseModel):
    normalized_text: str = Field(..., description="النص بعد التنقيح والتحويل للفصحى")


class NormalizedTranscriptionSegment(BaseModel):
    lesson_id: str = Field(..., min_length=1, description="معرف الدرس/المحاضرة الفريد")
    start_time: int = Field(..., ge=0, description="وقت بدء المقطع بالثواني")
    end_time: int = Field(..., ge=0, description="وقت نهاية المقطع بالثواني")
    normalized_text: str = Field(..., min_length=1, description="النص المفرغ والمنقح باللهجة الفصحى")
    youtube_url: str = Field(..., description="رابط اليوتيوب الخاص بالفيديو متضمناً طابع الوقت")

    # تحقق وتعديل على مستوى النموذج بالكامل (Model Validator - mode="after")
    @model_validator(mode="after")
    def validate_time_range_and_url(self) -> Self:
        # أ. التأكد من أن وقت النهاية أكبر من وقت البداية
        if self.end_time <= self.start_time:
            raise ValueError(f"وقت النهاية ({self.end_time}) يجب أن يكون أكبر من وقت البداية ({self.start_time}).")

        # ب. تنظيف واستخراج معرف اليوتيوب (Video ID) وإعادة صياغة الرابط بالشكل المطلوب
        # الروابط المدعومة: watch?v=ID أو youtu.be/ID
        match = YOUTUBE_REGEX.search(self.youtube_url)
        if not match:
            raise ValueError("رابط YouTube غير صالح. يجب أن يحتوي على معرف فيديو (Video ID) مكون من 11 حرفاً.")

        video_id = match.group(1)

        # ج. إعادة تركيب الرابط ليحتوي على طابع الوقت بالشكل الموحد: ?t={start_time}s
        self.youtube_url = f"https://youtu.be/{video_id}?t={self.start_time}s"

        return self

# -------------------------------------------------------------------
# نموذج البيانات الوصفية للدرس — يُمرَّر للـ Pipeline عند الاستيعاب
# -------------------------------------------------------------------
class LessonMetadata(BaseModel):
    """بيانات السياق الكاملة للدرس — تُستخدم لبناء allowed_entities في Qdrant."""
    lesson_id:   str
    lesson_ids:  list[str] = Field(default_factory=list)
    tenant_ids:  list[str] = Field(default=["default"])
    module_id:   str | None = None
    module_ids:  list[str] = Field(default_factory=list)
    unit_id:     str | None = None
    level_id:    str | None = None
    type_id:     str | None = None
    target_roles: list[str] = Field(default=["Admin", "Student"])
    # سيتم بناؤها تلقائياً من الحقول أعلاه
    allowed_entities: list[str] = Field(default_factory=list)

    def build_allowed_entities(self) -> "LessonMetadata":
        """يبني قائمة الكيانات المسموحة من حقول الـ metadata (يدعم موديولات ودروس متعددة)."""
        entities: set[str] = set()
        for t in self.tenant_ids:
            entities.add(f"tenant:{t}")

        # دعم موديول فردي أو مصفوفة موديولات
        if self.module_id:
            entities.add(f"module:{self.module_id}")
        for m in self.module_ids:
            if m:
                entities.add(f"module:{m}")

        if self.unit_id:
            entities.add(f"unit:{self.unit_id}")
        if self.level_id:
            entities.add(f"level:{self.level_id}")
        if self.type_id:
            entities.add(f"type:{self.type_id}")

        # دعم درس فردي أو مصفوفة دروس تشترك في نفس الفيديو
        if self.lesson_id:
            entities.add(f"lesson:{self.lesson_id}")
        for l in self.lesson_ids:
            if l:
                entities.add(f"lesson:{l}")

        for role in self.target_roles:
            entities.add(f"role:{role}")

        self.allowed_entities = sorted(list(entities))
        return self



# -------------------------------------------------------------------
# نموذج النقطة الكاملة التي تُرسل إلى Qdrant
# -------------------------------------------------------------------
class QdrantChunkPayload(BaseModel):
    """الـ Payload الكامل لكل نقطة (chunk) في Qdrant collection مع دعم المراجع المتعددة."""
    chunk_id:        str
    lesson_id:       str | None = None
    lesson_ids:      list[str] = Field(default_factory=list)
    content_type:    ContentType
    source_type:     SourceType
    source_url:      str                  # رابط يوتيوب مع timestamp
    start_time:      int | None = None    # بالثواني
    end_time:        int | None = None
    page_number:     int | None = None    # للـ PDF
    section_title:   str | None = None    # للـ PDF
    text_msa:        str                  # النص المنقح (للـ Embedding والعرض)
    text_original:   str                  # النص الخام (للتدقيق)
    tenant_ids:      list[str]
    module_id:       str | None = None
    module_ids:      list[str] = Field(default_factory=list)
    unit_id:         str | None = None
    level_id:        str | None = None
    type_id:         str | None = None
    video_id:        str | None = None
    playlist_id:     str | None = None
    target_roles:    list[str]
    allowed_entities: list[str]

    @model_validator(mode="after")
    def sync_multi_reference_fields(self) -> Self:
        """ضمان التوافق العكسي وتزامن lesson_ids و module_ids مع lesson_id و module_id."""
        if self.lesson_id and self.lesson_id not in self.lesson_ids:
            self.lesson_ids.append(self.lesson_id)
        if self.module_id and self.module_id not in self.module_ids:
            self.module_ids.append(self.module_id)
        return self


# -------------------------------------------------------------------
# PR-3: AI Content Generator Schemas (Admin/LMS Integration)
# -------------------------------------------------------------------
class QuizOption(BaseModel):
    id: str = Field(..., description="معرف الخيار (a, b, c, d)")
    text: str = Field(..., description="نص الخيار")

    @computed_field
    @property
    def option_id(self) -> str:
        """حقل توافقي لـ .NET C# DTO (OptionId)."""
        return self.id

    @computed_field
    @property
    def option_text(self) -> str:
        """حقل توافقي لـ .NET C# DTO."""
        return self.text

class QuizQuestion(BaseModel):
    id: int = Field(..., description="رقم السؤال في التسلسل")
    question: str = Field(..., description="نص السؤال")
    options: list[QuizOption] = Field(..., description="قائمة من 4 خيارات")
    correct_answer_id: str = Field(..., description="الإجابة الصحيحة (a, b, c, d)")
    explanation: str = Field(..., description="تفسير سبب صحة الإجابة (للتصحيح)")

    @computed_field
    @property
    def question_text(self) -> str:
        """حقل توافقي لـ .NET C# DTO (QuestionText)."""
        return self.question

    @computed_field
    @property
    def question_number(self) -> int:
        """حقل توافقي لـ .NET C# DTO (QuestionNumber)."""
        return self.id

class GeneratedQuiz(BaseModel):
    lesson_id: str = Field(..., description="معرف الدرس المرتبط بالاختبار")
    questions: list[QuizQuestion] = Field(..., description="الأسئلة المولدة")
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class SummaryTopic(BaseModel):
    title: str = Field(..., description="عنوان الموضوع الرئيسي")
    points: list[str] = Field(..., description="نقاط تفصيلية تشرح الموضوع")

class GeneratedSummary(BaseModel):
    lesson_id: str = Field(..., description="معرف الدرس المرتبط بالملخص")
    overview: str = Field(default="", description="نظرة عامة وشاملة تلخص الفكرة الأساسية للدرس")
    topics: list[SummaryTopic] = Field(..., description="المواضيع المستخرجة من الدرس")
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class AudioIngestRequestV2(BaseModel):
    youtube_url: str = Field(..., description="رابط فيديو اليوتيوب")
    lesson_id: str = Field(..., description="معرف الدرس الفريد")
    lesson_metadata: LessonMetadata | None = Field(None, description="بيانات الدرس الوصفية (اختياري)")

class WebhookPayload(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    lesson_id: str = Field(..., validation_alias=AliasChoices("lessonId", "lesson_id", "LessonId"), serialization_alias="lessonId", description="معرف الدرس المرتبط بالحدث")
    action: str = Field(..., description="نوع الإجراء (Updated / Deleted / Referenced)")
    video_url: str | None = Field(default=None, validation_alias=AliasChoices("videoUrl", "video_url", "VideoUrl"), description="رابط الفيديو (في حال الربط بمحتوى قائم)")
    module_id: str | None = Field(default=None, validation_alias=AliasChoices("moduleId", "module_id", "ModuleId"), description="معرف الموديول المرتبط")
    unit_id: str | None = Field(default=None, validation_alias=AliasChoices("unitId", "unit_id", "UnitId"), description="معرف الوحدة المرتبطة")

    @property
    def lessonId(self) -> str:
        return self.lesson_id


class LessonReferenceRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    lesson_id: str = Field(..., validation_alias=AliasChoices("lessonId", "lesson_id", "LessonId"), description="معرف الدرس الجديد")
    source_video_url: str = Field(..., validation_alias=AliasChoices("videoUrl", "video_url", "VideoUrl", "sourceVideoUrl", "source_video_url"), description="رابط الفيديو القائم")
    module_id: str | None = Field(default=None, validation_alias=AliasChoices("moduleId", "module_id", "ModuleId"), description="معرف الموديول الجديد")
    unit_id: str | None = Field(default=None, validation_alias=AliasChoices("unitId", "unit_id", "UnitId"), description="معرف الوحدة الجديدة")


class LessonReferenceResponse(BaseModel):
    status: str = "success"
    message: str
    points_linked: int
    video_id: str
    lesson_id: str
    module_id: str | None = None


class SyncFailedRequest(BaseModel):
    lesson_ids: list[str] = Field(..., min_length=1, description="قائمة بمعرفات الدروس المراد إعادة مزامنتها ومعالجتها")


class SyncFailedResponse(BaseModel):
    status: str = "accepted"
    lessons_queued: list[str]
    count: int
    message: str = "Reconciliation and re-ingestion scheduled successfully"


class LessonStatusResponse(BaseModel):
    lesson_id: str
    status: str = Field(..., description="حالة المعالجة: idle | processing | completed | failed")
    chunks_count: int = Field(default=0, description="عدد الـ Chunks المخزنة في Qdrant")
    current_stage: str | None = Field(default=None, description="المرحلة الحالية من معالجة الـ Pipeline")
    error: str | None = Field(default=None, description="رسالة الخطأ في حال الفشل")
    can_generate_quiz: bool = Field(default=False, description="هل يمكن توليد كويز للدرس")
    can_generate_summary: bool = Field(default=False, description="هل يمكن توليد ملخص للدرس")
    last_updated: str | None = Field(default=None, description="وقت آخر حدث مسجل")
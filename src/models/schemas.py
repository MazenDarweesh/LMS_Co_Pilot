import re
from datetime import datetime, timezone
from pydantic import BaseModel, Field, field_validator, model_validator
from typing import Self
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
        youtube_regex = r"(?:v=|\/)([a-zA-Z0-9_-]{11})"
        match = re.search(youtube_regex, self.youtube_url)
        if not match:
            raise ValueError("رابط YouTube غير صالح. يجب أن يحتوي على معرف فيديو (Video ID) مكون من 11 حرفاً.")

        video_id = match.group(1)

        # ج. إعادة تركيب الرابط ليحتوي على طابع الوقت بالشكل الموحد: ?t={start_time}s
        self.youtube_url = f"https://youtu.be/{video_id}?t={self.start_time}s"

        return self

from src.models.entities import ContentType, SourceType

# -------------------------------------------------------------------
# نموذج البيانات الوصفية للدرس — يُمرَّر للـ Pipeline عند الاستيعاب
# -------------------------------------------------------------------
class LessonMetadata(BaseModel):
    """بيانات السياق الكاملة للدرس — تُستخدم لبناء allowed_entities في Qdrant."""
    lesson_id:   str
    tenant_ids:  list[str] = Field(default=["default"])
    module_id:   str | None = None
    unit_id:     str | None = None
    level_id:    str | None = None
    type_id:     str | None = None
    target_roles: list[str] = Field(default=["Admin", "Student"])
    # سيتم بناؤها تلقائياً من الحقول أعلاه
    allowed_entities: list[str] = Field(default_factory=list)

    def build_allowed_entities(self) -> "LessonMetadata":
        """يبني قائمة الكيانات المسموحة من حقول الـ metadata."""
        entities: list[str] = []
        for t in self.tenant_ids:
            entities.append(f"tenant:{t}")
        if self.module_id:
            entities.append(f"module:{self.module_id}")
        if self.unit_id:
            entities.append(f"unit:{self.unit_id}")
        if self.level_id:
            entities.append(f"level:{self.level_id}")
        if self.type_id:
            entities.append(f"type:{self.type_id}")
        entities.append(f"lesson:{self.lesson_id}")
        for role in self.target_roles:
            entities.append(f"role:{role}")
        self.allowed_entities = entities
        return self


# -------------------------------------------------------------------
# نموذج النقطة الكاملة التي تُرسل إلى Qdrant
# -------------------------------------------------------------------
class QdrantChunkPayload(BaseModel):
    """الـ Payload الكامل لكل نقطة (chunk) في Qdrant collection."""
    chunk_id:        str
    lesson_id:       str | None
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
    unit_id:         str | None = None
    level_id:        str | None = None
    type_id:         str | None = None
    video_id:        str | None = None
    playlist_id:     str | None = None
    target_roles:    list[str]
    allowed_entities: list[str]

# -------------------------------------------------------------------
# PR-3: AI Content Generator Schemas (Admin/LMS Integration)
# -------------------------------------------------------------------
class QuizOption(BaseModel):
    id: str = Field(..., description="معرف الخيار (a, b, c, d)")
    text: str = Field(..., description="نص الخيار")

class QuizQuestion(BaseModel):
    id: int = Field(..., description="رقم السؤال في التسلسل")
    question: str = Field(..., description="نص السؤال")
    options: list[QuizOption] = Field(..., description="قائمة من 4 خيارات")
    correct_answer_id: str = Field(..., description="الإجابة الصحيحة (a, b, c, d)")
    explanation: str = Field(..., description="تفسير سبب صحة الإجابة (للتصحيح)")

class GeneratedQuiz(BaseModel):
    lesson_id: str = Field(..., description="معرف الدرس المرتبط بالاختبار")
    questions: list[QuizQuestion] = Field(..., description="الأسئلة المولدة")
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class SummaryTopic(BaseModel):
    title: str = Field(..., description="عنوان الموضوع الرئيسي")
    points: list[str] = Field(..., description="نقاط تفصيلية تشرح الموضوع")

class GeneratedSummary(BaseModel):
    lesson_id: str = Field(..., description="معرف الدرس المرتبط بالملخص")
    topics: list[SummaryTopic] = Field(..., description="المواضيع المستخرجة من الدرس")
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class AudioIngestRequestV2(BaseModel):
    youtube_url: str = Field(..., description="رابط فيديو اليوتيوب")
    lesson_id: str = Field(..., description="معرف الدرس الفريد")
    lesson_metadata: LessonMetadata | None = Field(None, description="بيانات الدرس الوصفية (اختياري)")

class WebhookPayload(BaseModel):
    lessonId: str = Field(..., description="معرف الدرس المرتبط بالحدث")
    action: str = Field(..., description="نوع الإجراء (Updated / Deleted)")
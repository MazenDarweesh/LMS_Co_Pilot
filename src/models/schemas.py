import re
from pydantic import BaseModel, Field, field_validator, model_validator
from typing import Self

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
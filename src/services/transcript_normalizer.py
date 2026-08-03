import json
import structlog
from google import genai
from google.genai import types
from src.core.config import settings
from src.models.schemas import NormalizedTranscriptionSegment, LLMNormalizationResponse
from src.core.prompts import GEMINI_NORMALIZATION_PROMPT

logger = structlog.get_logger()

# تهيئة عميل Gemini باستخدام الـ SDK الجديد (google-genai)
gemini_client = genai.Client(api_key=settings.GEMINI_API_KEY)

class TranscriptNormalizerService:
    async def normalize_segment(
        self,
        raw_text: str,
        start_time: int,
        end_time: int,
        lesson_id: str,
        video_id: str
    ) -> NormalizedTranscriptionSegment:

        log = logger.bind(lesson_id=lesson_id, start_time=start_time)
        log.info("Starting text normalization via Gemini")

        # بناء الرسالة التي ستُرسل للنموذج
        prompt = f"{GEMINI_NORMALIZATION_PROMPT}\n\nالنص الأصلي المراد تنقيحه:\n{raw_text}"

        # استدعاء Gemini بشكل غير متزامن مع إجباره على إرجاع JSON يطابق الموديل الخاص بنا
        response = await gemini_client.aio.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=LLMNormalizationResponse,
                temperature=0.1, # درجة إبداع منخفضة لضمان الدقة وعدم الهلوسة
            ),
        )

        # الـ Validation النهائي من Pydantic (يحول الـ JSON String إلى كائن Python)
        # نستخدم (response.text or "{}") لحل مشكلة النوع في Pyrefly (لتفادي القيمة None)
        response_data = json.loads(response.text or "{}")

        # تجميع البيانات
        final_data = {
            "lesson_id": lesson_id,
            "start_time": start_time,
            "end_time": end_time,
            "youtube_url": video_id, # سيقوم Pydantic Validator بتحويله للرابط الكامل تلقائياً
            "normalized_text": response_data.get("normalized_text", raw_text)
        }

        normalized_segment = NormalizedTranscriptionSegment(**final_data)

        log.info("Normalization completed successfully")
        return normalized_segment

transcript_normalizer = TranscriptNormalizerService()
import re
import json
import structlog
from google import genai
from google.genai import types
from google.genai.errors import ServerError, ClientError
from tenacity import retry, stop_after_attempt, RetryCallState, retry_if_exception_type
from src.core.config import settings
from src.models.schemas import NormalizedTranscriptionSegment, LLMNormalizationResponse
from src.core.prompts import GEMINI_NORMALIZATION_PROMPT

logger = structlog.get_logger()

def _wait_from_retry_after(retry_state: RetryCallState) -> float:
    """
    Best Practice: قراءة وقت الانتظار المطلوب مباشرةً من رسالة خطأ الـ API (retry-after pattern).
    المصدر: https://ai.google.dev/gemini-api/docs/rate-limits
    بدلاً من الخمن بوقت الانتظار، نسمع للـ Server الذي يخبرنا بالضبط كم ننتظر.
    """
    exc = retry_state.outcome.exception()
    if exc:
        # محاولة استخراج قيمة retryDelay من نص رسالة الخطأ (مثال: "Please retry in 37.5s.")
        match = re.search(r"retry in (\d+\.?\d*)\s*s", str(exc), re.IGNORECASE)
        if match:
            delay = float(match.group(1)) + 2.0  # نضيف ثانيتين كهامش أمان
            logger.info("API requested retry delay", delay_seconds=delay)
            return delay
    # fallback: إذا لم نجد قيمة retryDelay، ننتظر 30 ثانية كقيمة افتراضية آمنة
    return 30.0


# تهيئة عميل Gemini باستخدام الـ SDK الجديد (google-genai)
gemini_client = genai.Client(api_key=settings.GEMINI_API_KEY)

class TranscriptNormalizerService:
    # إعادة المحاولة الذكية: نقرأ وقت الانتظار من رسالة الـ API مباشرةً بدلاً من الخمن
    @retry(
        stop=stop_after_attempt(5),
        wait=_wait_from_retry_after,  # type: ignore
        retry=retry_if_exception_type((ServerError, ClientError)),
        reraise=True
    )
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
            model="gemini-3.5-flash-lite",
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
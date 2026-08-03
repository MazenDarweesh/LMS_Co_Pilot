import structlog
from typing import Any
from groq import AsyncGroq
import aiofiles  # type: ignore
from src.models.schemas import AudioTranscriptionResponse
from src.core.config import settings
from src.core.prompts import WHISPER_ERP_DOMAIN_PROMPT
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from groq import RateLimitError

logger = structlog.get_logger()

# تهيئة عميل Groq غير المتزامن باستخدام مفتاح الـ API
groq_client = AsyncGroq(api_key=settings.GROQ_API_KEY)

class AudioService:
    def __init__(self):
        # استدعاء الـ Prompt من ملف الـ Prompts المخصص
        self.domain_prompt = WHISPER_ERP_DOMAIN_PROMPT

    # استخدام Tenacity لإعادة المحاولة عند مواجهة Rate Limit (429) مع انتظار تصاعدي (Exponential Backoff)
    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(RateLimitError),
        reraise=True
    )
    async def transcribe_audio(self, file_path: str) -> AudioTranscriptionResponse:
        # ربط مسار الملف بالـ Logger لكي يظهر تلقائياً في حالة حدوث أي خطأ في الـ Middleware
        log = logger.bind(file_path=file_path)
        log.info("Starting Groq Whisper transcription")

        # قراءة الملف بشكل غير متزامن لتفادي تجميد السيرفر (Async I/O)
        async with aiofiles.open(file_path, "rb") as audio_file:
            file_content = await audio_file.read()

        # إرسال الملف إلى Groq Whisper-large-v3
        transcription: Any = await groq_client.audio.transcriptions.create(
            file=(file_path, file_content),
            model="whisper-large-v3",
            prompt=self.domain_prompt,
            response_format="verbose_json", # صيغة verbose ترجع تفاصيل دقيقة مثل مدة المقطع
            language="ar" # إجبار النموذج على أن اللغة الأصلية هي العربية
        )

        log.info("Groq transcription completed successfully", duration=transcription.duration)

        # إرجاع الاستجابة النهائية
        return AudioTranscriptionResponse(
            text=transcription.text,
            duration=transcription.duration
        )

audio_service = AudioService()
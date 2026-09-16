import asyncio
import json
import time
import structlog
from google import genai
from google.genai import types
from qdrant_client.models import Filter, FieldCondition, MatchValue

from src.core.config import settings
from src.core.prompts import QUIZ_GENERATION_PROMPT, SUMMARY_GENERATION_PROMPT
from src.models.schemas import GeneratedQuiz, GeneratedSummary
from src.services.qdrant_service import qdrant_service
from src.core.metrics import record_content_generation_duration, record_token_usage

logger = structlog.get_logger()

# Assuming a simple dependency initialization, typical for FastAPI services.
class LessonContentService:
    def __init__(self):
        self._gemini_client = genai.Client(api_key=settings.GEMINI_API_KEY)

    async def generate_quiz(self, lesson_id: str, num_questions: int = 5) -> GeneratedQuiz:
        """
        توليد اختبار (Quiz) مقسم زمنياً لضمان تغطية الدرس بالكامل (Anti-Clustering).
        """
        t0 = time.time()
        logger.info("Generating Quiz", lesson_id=lesson_id, num_questions=num_questions)
        
        lesson_filter = Filter(
            must=[FieldCondition(key="lesson_id", match=MatchValue(value=lesson_id))]
        )
        
        # جلب أكبر عدد ممكن لضمان التغطية، ثم ترتيبهم برمجياً
        records = await qdrant_service.client.scroll(
            collection_name=settings.QDRANT_COLLECTION,
            scroll_filter=lesson_filter,
            limit=50,
            with_payload=True
        )
        
        chunks = records[0]
        if not chunks:
            raise ValueError(f"لا يوجد محتوى مسجل للدرس {lesson_id}")
            
        # ترتيب الـ chunks حسب وقت البداية
        chunks = sorted(chunks, key=lambda x: x.payload.get("start_time", 0))
        
        # حد أدنى للمحتوى: يجب أن يكون عدد الـ chunks لا يقل عن عدد الأسئلة المطلوبة
        if len(chunks) < num_questions:
            raise ValueError(
                f"محتوى الدرس '{lesson_id}' غير كافٍ لتوليد {num_questions} أسئلة. "
                f"وُجد {len(chunks)} chunk(s) فقط. يُرجى التأكد من اكتمال استيعاب الدرس."
            )
        
        # أخذ أفضل 20 chunk (أو أقل إذا كان الدرس قصيراً)
        chunks = chunks[:20]
        
        # 2. تجميع النص في مجموعات
        chunk_texts = [f"[{i+1}] {c.payload.get('text_msa', '')}" for i, c in enumerate(chunks)]
        context_str = "\n".join(chunk_texts)
        
        # 3. بناء الـ Prompt
        prompt = QUIZ_GENERATION_PROMPT.format(
            num_groups=num_questions,
            chunked_context=context_str
        )
        
        # 4. الاستدعاء عبر asyncio.to_thread
        response = await asyncio.to_thread(
            self._gemini_client.models.generate_content,
            model=settings.GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.3, # درجة حرارة منخفضة لضمان الدقة
                response_schema=GeneratedQuiz.model_json_schema()
            )
        )
        
        try:
            quiz_data = json.loads(response.text)
            # دمج lesson_id مع النتيجة
            quiz_data["lesson_id"] = lesson_id
            duration = round(time.time() - t0, 3)
            record_content_generation_duration("quiz", "generate", duration)
            if hasattr(response, "usage_metadata") and response.usage_metadata:
                record_token_usage(
                    prompt_tokens=getattr(response.usage_metadata, "prompt_token_count", 0) or 0,
                    completion_tokens=getattr(response.usage_metadata, "candidates_token_count", 0) or 0,
                    total_tokens=getattr(response.usage_metadata, "total_token_count", 0) or 0,
                )
            logger.info("Quiz generated successfully 🎯", lesson_id=lesson_id, duration_seconds=duration, questions_count=len(quiz_data.get("questions", [])))
            return GeneratedQuiz(**quiz_data)
        except Exception as e:
            logger.error("Failed to parse Quiz JSON", error=str(e), response_text=response.text)
            raise ValueError("فشل في استخراج الاختبار من رد الذكاء الاصطناعي")

    async def generate_summary(self, lesson_id: str) -> GeneratedSummary:
        """
        توليد ملخص باستخدام تقنية Pyramid Summarization لمنع تركيز النماذج على الأطراف فقط.
        """
        t0 = time.time()
        logger.info("Generating Summary", lesson_id=lesson_id)
        
        lesson_filter = Filter(
            must=[FieldCondition(key="lesson_id", match=MatchValue(value=lesson_id))]
        )
        
        records = await qdrant_service.client.scroll(
            collection_name=settings.QDRANT_COLLECTION,
            scroll_filter=lesson_filter,
            limit=15,
            with_payload=True
        )
        
        chunks = records[0]
        if not chunks:
            raise ValueError(f"لا يوجد محتوى مسجل للدرس {lesson_id}")
        
        # حد أدنى للملخص: 3 chunks على الأقل لضمان جودة المحتوى
        MIN_CHUNKS_FOR_SUMMARY = 3
        if len(chunks) < MIN_CHUNKS_FOR_SUMMARY:
            raise ValueError(
                f"محتوى الدرس '{lesson_id}' غير كافٍ لتوليد ملخص. "
                f"وُجد {len(chunks)} chunk(s) فقط، والحد الأدنى هو {MIN_CHUNKS_FOR_SUMMARY}."
            )
            
        chunk_texts = [f"- {c.payload.get('text_msa', '')}" for c in chunks]
        context_str = "\n".join(chunk_texts)
        
        prompt = SUMMARY_GENERATION_PROMPT.format(
            num_topics=3, # حسب الـ ADR-06 اخترنا 3 مواضيع رئيسية
            context_chunks=context_str
        )
        
        response = await asyncio.to_thread(
            self._gemini_client.models.generate_content,
            model=settings.GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.4,
                response_schema=GeneratedSummary.model_json_schema()
            )
        )
        
        try:
            summary_data = json.loads(response.text)
            summary_data["lesson_id"] = lesson_id
            duration = round(time.time() - t0, 3)
            record_content_generation_duration("summary", "generate", duration)
            if hasattr(response, "usage_metadata") and response.usage_metadata:
                record_token_usage(
                    prompt_tokens=getattr(response.usage_metadata, "prompt_token_count", 0) or 0,
                    completion_tokens=getattr(response.usage_metadata, "candidates_token_count", 0) or 0,
                    total_tokens=getattr(response.usage_metadata, "total_token_count", 0) or 0,
                )
            logger.info("Summary generated successfully 📝", lesson_id=lesson_id, duration_seconds=duration, topics_count=len(summary_data.get("topics", [])))
            return GeneratedSummary(**summary_data)
        except Exception as e:
            logger.error("Failed to parse Summary JSON", error=str(e), response_text=response.text)
            raise ValueError("فشل في استخراج الملخص من رد الذكاء الاصطناعي")

lesson_content_service = LessonContentService()

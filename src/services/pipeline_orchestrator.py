import os
import json
import asyncio
import aiofiles
import structlog
from pathlib import Path
from typing import List
from src.models.schemas import NormalizedTranscriptionSegment
from src.services.audio_downloader import audio_downloader
from src.services.transcription_service import TranscriptionService
from src.services.transcript_normalizer import transcript_normalizer
from src.db.event_store import EventStoreRepository

logger = structlog.get_logger()

CHECKPOINT_DIR = Path("downloads/checkpoints")

class PipelineOrchestrator:
    def __init__(self, concurrency_limit: int = 3):
        # السماح بـ 3 عمليات فقط في نفس الوقت لتجنب أخطاء Rate Limit
        self.semaphore = asyncio.Semaphore(concurrency_limit)
        self.transcription_service = TranscriptionService()

    async def _process_single_chunk(self, chunk_path: str, lesson_id: str, youtube_url: str, chunk_index: int, db_pool, session_id: str, chunk_duration_ms: int = 120*1000) -> NormalizedTranscriptionSegment:
        """مهمة داخلية لمعالجة مقطع صوتي واحد بالكامل."""
        async with self.semaphore:
            log = logger.bind(lesson_id=lesson_id, chunk_index=chunk_index)
            log.info("Processing chunk started")

            # 1. إنشاء مسارات الـ Checkpoints
            checkpoint_file = CHECKPOINT_DIR / f"{lesson_id}_chunk_{chunk_index}.json"
            temp_file = CHECKPOINT_DIR / f"{lesson_id}_chunk_{chunk_index}.tmp"

            # 2. التحقق من وجود الـ Checkpoint (استرجاع ذكي)
            if checkpoint_file.exists():
                try:
                    async with aiofiles.open(checkpoint_file, "r", encoding="utf-8") as f:
                        data = json.loads(await f.read())
                    log.info("Checkpoint hit - loading chunk from disk")
                    return NormalizedTranscriptionSegment(**data)
                except Exception as e:
                    log.warning("Corrupted checkpoint detected, reprocessing", error=str(e))

            async with db_pool.acquire() as db:
                event_store = EventStoreRepository(db)

                # 3. الاستماع (الآذان - Groq)
                await event_store.insert_event(session_id, "GroqWhisper", "TRANSCRIPTION_STARTED", {"chunk_index": chunk_index})
                transcription_segments = await self.transcription_service.transcribe(chunk_path)
                
                # استخراج النص الكامل من القطع
                raw_text = " ".join([seg["text"] for seg in transcription_segments])
                
                # حساب الوقت التقريبي للبداية والنهاية بناءً على الترتيب
                start_time = int((chunk_index * chunk_duration_ms) / 1000)
                end_time = int(start_time + (chunk_duration_ms / 1000))

                # 4. التنقيح (العقل - Gemini)
                await event_store.insert_event(session_id, "GeminiFlash", "NORMALIZATION_STARTED", {"chunk_index": chunk_index})
                
            normalized_segment = await transcript_normalizer.normalize_segment(
                raw_text=raw_text,
                start_time=start_time,
                end_time=end_time,
                lesson_id=lesson_id,
                video_id=youtube_url  # Pydantic schema will extract the ID and format it automatically
            )

            # 5. حفظ الـ Checkpoint بطريقة آمنة (Atomic Write)
            os.makedirs(CHECKPOINT_DIR, exist_ok=True)
            async with aiofiles.open(temp_file, "w", encoding="utf-8") as f:
                await f.write(json.dumps(normalized_segment.model_dump(), ensure_ascii=False, indent=4))
            
            # تغيير الاسم ليكون الملف المعتمد
            os.replace(temp_file, checkpoint_file)

            log.info("Processing chunk finished and checkpoint saved")
            return normalized_segment

    async def run_audio_pipeline(self, youtube_url: str, lesson_id: str, db_pool) -> List[NormalizedTranscriptionSegment]:
        """المنسق الرئيسي (Orchestrator) الذي يدير العملية من الألف للياء."""
        log = logger.bind(lesson_id=lesson_id, youtube_url=youtube_url)
        log.info("Pipeline started")
        
        session_id = f"sess_{lesson_id}"

        # استخدام مهلة أقصاها 10 دقائق لكامل الـ Pipeline لضمان عدم تجمد السيرفر
        async with asyncio.timeout(600):
            async with db_pool.acquire() as db:
                event_store = EventStoreRepository(db)
                
                try:
                    await event_store.insert_event(session_id, "System", "PIPELINE_STARTED", {"url": youtube_url})

                    # 1. التحميل
                    audio_file_path = await audio_downloader.download_audio(youtube_url)
                    await event_store.insert_event(session_id, "AudioService", "DOWNLOAD_COMPLETE", {"file": audio_file_path})

                    # 2. التقطيع
                    chunk_paths = await audio_downloader.chunk_audio(audio_file_path)
                    await event_store.insert_event(session_id, "AudioService", "CHUNKING_COMPLETE", {"chunks_count": len(chunk_paths)})

                    # 3. المعالجة المتزامنة الآمنة (Structured Concurrency)
                    async with asyncio.TaskGroup() as tg:
                        tasks = [
                            tg.create_task(
                                self._process_single_chunk(
                                    chunk_path=chunk_path,
                                    lesson_id=lesson_id,
                                    youtube_url=youtube_url,
                                    chunk_index=i,
                                    db_pool=db_pool,
                                    session_id=session_id
                                )
                            )
                            for i, chunk_path in enumerate(chunk_paths)
                        ]

                    # تجميع النتائج بعد انتهاء جميع المهام
                    results = [task.result() for task in tasks]

                    # ترتيب النتائج بناءً على وقت البداية لضمان تسلسل الدرس
                    results.sort(key=lambda x: x.start_time)

                    await event_store.insert_event(session_id, "System", "PIPELINE_COMPLETE", {"status": "success", "total_chunks": len(results)})
                    log.info("Pipeline completed successfully", total_chunks=len(results))
                    
                    # Cleanup audio files
                    if os.path.exists(audio_file_path):
                        os.remove(audio_file_path)
                    for chunk_path in chunk_paths:
                        if os.path.exists(chunk_path):
                            os.remove(chunk_path)
                            
                    return results
                    
                except Exception as e:
                    logger.error("Pipeline failed", error=str(e), session_id=session_id)
                    await event_store.insert_event(session_id, "System", "PIPELINE_FAILED", {"error": str(e)})
                    raise e

pipeline_orchestrator = PipelineOrchestrator()
import os
import json
import hashlib
import asyncio
import time
import aiofiles
import structlog
from pathlib import Path
from typing import List
from src.models.schemas import NormalizedTranscriptionSegment, LessonMetadata
from src.services.audio_downloader import audio_downloader
from src.services.transcription_service import TranscriptionService
from src.services.transcript_normalizer import transcript_normalizer
from src.services.lms_client import lms_client_service
from src.utils.arabic_speech_utils import normalize_arabic_text_leaderboard
from src.db.event_store import EventStoreRepository
from src.core.metrics import (
    record_video_ingestion_stage,
    record_video_ingestion_completed,
    record_video_ingestion_failed,
    set_video_ingestion_in_flight,
)

logger = structlog.get_logger()


def make_chunk_id(lesson_id: str, chunk_index: int) -> str:
    """
    يُولّد chunk_id حتمياً (Deterministic) من lesson_id + رقم المقطع.
    نفس المدخلات = نفس الـ ID دائماً.

    الهدف: ضمان أن إعادة تشغيل الـ Pipeline أو حدوث Crash ثم Retry
    لن يُنتج نقاطاً مكررة في Qdrant — الـ upsert سيُحدّث النقطة الموجودة.
    """
    raw = f"{lesson_id}::chunk::{chunk_index}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]

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
                t_trans = time.perf_counter()
                transcription_segments = await self.transcription_service.transcribe(chunk_path)
                record_video_ingestion_stage("transcription", time.perf_counter() - t_trans)
                
                # استخراج النص الكامل من القطع
                raw_text = " ".join([seg["text"] for seg in transcription_segments])
                
                # حساب الوقت التقريبي للبداية والنهاية بناءً على الترتيب
                start_time = int((chunk_index * chunk_duration_ms) / 1000)
                end_time = int(start_time + (chunk_duration_ms / 1000))

                # 4. التنقيح (العقل - Gemini)
                await event_store.insert_event(session_id, "GeminiFlash", "NORMALIZATION_STARTED", {"chunk_index": chunk_index})
                
            t_norm = time.perf_counter()
            normalized_segment = await transcript_normalizer.normalize_segment(
                raw_text=raw_text,
                start_time=start_time,
                end_time=end_time,
                lesson_id=lesson_id,
                video_id=youtube_url  # Pydantic schema will extract the ID and format it automatically
            )
            record_video_ingestion_stage("normalization", time.perf_counter() - t_norm)

            # 5. حفظ الـ Checkpoint بطريقة آمنة (Atomic Write)
            os.makedirs(CHECKPOINT_DIR, exist_ok=True)
            async with aiofiles.open(temp_file, "w", encoding="utf-8") as f:
                await f.write(json.dumps(normalized_segment.model_dump(), ensure_ascii=False, indent=4))
            
            # تغيير الاسم ليكون الملف المعتمد
            os.replace(temp_file, checkpoint_file)

            log.info("Processing chunk finished and checkpoint saved")
            return normalized_segment

    async def run_audio_pipeline(
        self,
        youtube_url: str,
        lesson_id: str,
        db_pool,
        lesson_metadata: "LessonMetadata | None" = None,
    ) -> List[NormalizedTranscriptionSegment]:
        """المنسق الرئيسي (Orchestrator) الذي يدير العملية من الألف للياء."""
        log = logger.bind(lesson_id=lesson_id, youtube_url=youtube_url)
        log.info("Pipeline started")
        
        session_id = f"sess_{lesson_id}"
        set_video_ingestion_in_flight(1)
        pipeline_start_time = time.perf_counter()

        # استخدام مهلة أقصاها 10 دقائق لكامل الـ Pipeline لضمان عدم تجمد السيرفر
        async with asyncio.timeout(600):
            async with db_pool.acquire() as db:
                event_store = EventStoreRepository(db)
                
                audio_file_path: str | None = None
                chunk_paths: list[str] = []

                try:
                    await event_store.insert_event(session_id, "System", "PIPELINE_STARTED", {"url": youtube_url})

                    # 1. التحميل
                    t_dl = time.perf_counter()
                    audio_file_path = await audio_downloader.download_audio(youtube_url)
                    record_video_ingestion_stage("download", time.perf_counter() - t_dl)
                    await event_store.insert_event(session_id, "AudioService", "DOWNLOAD_COMPLETE", {"file": audio_file_path})

                    # 2. التقطيع
                    t_chunk = time.perf_counter()
                    chunk_paths = await audio_downloader.chunk_audio(audio_file_path)
                    record_video_ingestion_stage("chunking", time.perf_counter() - t_chunk)
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

                    # ④ التخزين في Qdrant (Embedding + Upsert) بشكل متزامن
                    if results:
                        from src.services.qdrant_service import qdrant_service
                        from src.services.embedding_service import embedding_service
                        from src.models.schemas import QdrantChunkPayload, LessonMetadata
                        from src.models.entities import ContentType, SourceType
                        import uuid

                        meta = lesson_metadata or LessonMetadata(
                            lesson_id=lesson_id,
                            tenant_ids=["default"],
                        )
                        meta.build_allowed_entities()

                        # دالة مساعدة لتجهيز نقطة واحدة (Embedding + Payload)
                        async def prepare_point(seg):
                            # 2026 Best Practice (Arabic Speech AI Research §13.6 & §2):
                            # Apply Leaderboard normalization BEFORE embedding to ensure
                            # the indexed embedding space is consistent with query normalization.
                            # This eliminates hamza/alif/ya variance in the vector space.
                            text_to_embed = normalize_arabic_text_leaderboard(seg.normalized_text)
                            dense, sparse = await embedding_service.get_both_embeddings(text_to_embed)
                            payload = QdrantChunkPayload(
                                # ✅ Fix: Deterministic ID — prevents duplicate Qdrant points on retry/re-run
                                chunk_id=make_chunk_id(lesson_id, results.index(seg)),
                                lesson_id=lesson_id,
                                content_type=ContentType.VIDEO_CHUNK,
                                source_type=SourceType.YOUTUBE,
                                source_url=seg.youtube_url,
                                start_time=seg.start_time,
                                end_time=seg.end_time,
                                text_msa=seg.normalized_text,
                                text_original=seg.normalized_text,
                                tenant_ids=meta.tenant_ids,
                                module_id=meta.module_id,
                                unit_id=meta.unit_id,
                                level_id=meta.level_id,
                                type_id=meta.type_id,
                                target_roles=meta.target_roles,
                                allowed_entities=meta.allowed_entities,
                            )
                            return payload, dense, sparse

                        # تنفيذ التضمين لكل المقاطع بالتوازي باستخدام asyncio.gather
                        # هذا سيجعل معالجة الفيديوهات الطويلة (> 1 ساعة) أسرع بكثير!
                        t_emb = time.perf_counter()
                        prepared_points = await asyncio.gather(*(prepare_point(seg) for seg in results))
                        record_video_ingestion_stage("embedding", time.perf_counter() - t_emb)
                        
                        payloads = [p[0] for p in prepared_points]
                        dense_vecs = [p[1] for p in prepared_points]
                        sparse_vecs = [p[2] for p in prepared_points]

                        t_upsert = time.perf_counter()
                        await qdrant_service.upsert_chunks(payloads, dense_vecs, sparse_vecs)
                        record_video_ingestion_stage("qdrant_upsert", time.perf_counter() - t_upsert)

                        await event_store.insert_event(
                            session_id, "QdrantService", "QDRANT_UPSERT_COMPLETE",
                            {"chunks_count": len(payloads)}
                        )

                    total_duration = time.perf_counter() - pipeline_start_time
                    record_video_ingestion_completed(total_duration, len(results))

                    await event_store.insert_event(session_id, "System", "PIPELINE_COMPLETE", {"status": "success", "total_chunks": len(results)})
                    log.info("Pipeline completed successfully", total_chunks=len(results), duration_seconds=round(total_duration, 2))
                    
                    # 🔔 Notify LMS backend of completion via webhook callback
                    asyncio.create_task(lms_client_service.notify_lesson_ai_status(
                        lesson_id=lesson_id,
                        status="Completed",
                        total_chunks=len(results)
                    ))
                    
                    return results
                    
                except Exception as e:
                    total_duration = time.perf_counter() - pipeline_start_time
                    record_video_ingestion_failed(total_duration)
                    logger.error("Pipeline failed", error=str(e), session_id=session_id, duration_seconds=round(total_duration, 2))
                    await event_store.insert_event(session_id, "System", "PIPELINE_FAILED", {"error": str(e)})
                    # 🔔 Notify LMS backend of failure via webhook callback
                    asyncio.create_task(lms_client_service.notify_lesson_ai_status(
                        lesson_id=lesson_id,
                        status="Failed",
                        error=str(e)
                    ))
                    raise e
                finally:
                    set_video_ingestion_in_flight(-1)
                    # 🧹 تنظيف الملفات الصوتية المؤقتة دائماً حتى لو فشل الـ Pipeline لمنع امتلاء القرص
                    if audio_file_path and os.path.exists(audio_file_path):
                        try:
                            os.remove(audio_file_path)
                        except OSError:
                            pass
                    for chunk_path in chunk_paths:
                        if os.path.exists(chunk_path):
                            try:
                                os.remove(chunk_path)
                            except OSError:
                                pass

pipeline_orchestrator = PipelineOrchestrator()
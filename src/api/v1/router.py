import asyncio
from fastapi import APIRouter, BackgroundTasks, Request, Depends
from sse_starlette.sse import EventSourceResponse
from pydantic import BaseModel

from src.models.schemas import (
    AudioTranscriptionRequest, AudioTranscriptionResponse,
    RAGQueryRequest, RAGQueryResponse, AudioIngestRequest
)
from src.services.audio_service import audio_service
from src.services.rag_service import rag_service

from src.core.middleware import limiter
from src.api.dependencies import get_event_store
from src.db.event_store import EventStoreRepository

router = APIRouter(prefix="/v1", tags=["V1 API"])

# ==============================================================================
# Legacy Endpoints (For Testing/Isolated services)
# ==============================================================================

@router.post("/transcribe", response_model=AudioTranscriptionResponse)
async def transcribe(request: AudioTranscriptionRequest):
    return await audio_service.transcribe_audio(request.file_path)

@router.post("/query-rag", response_model=RAGQueryResponse)
async def query_rag(request: RAGQueryRequest):
    return await rag_service.query_rag(request.query, request.limit)

# ==============================================================================
# 2026 Production Architecture: Background Ingestion & SSE Streaming
# ==============================================================================

async def run_pipeline_task_dummy(youtube_url: str, lesson_id: str, db_pool):
    """
    محاكاة (Mock) لعملية تحميل وتقطيع الفيديو وتفريغه.
    """
    session_id = f"sess_{lesson_id}"
    
    # 🚨 Best Practice: BackgroundTasks يجب أن تفتح اتصالها الخاص بقاعدة البيانات
    # لأن اتصال الـ Depends يتم إغلاقه بمجرد انتهاء الـ HTTP Request.
    async with db_pool.acquire() as db:
        event_store = EventStoreRepository(db)
        
        # 1. Start
        await event_store.insert_event(session_id, "System", "PIPELINE_STARTED", {"url": youtube_url})
        await asyncio.sleep(1) # تم تقليل الوقت لتسريع الاختبارات
        
        # 2. Download
        await event_store.insert_event(session_id, "Downloader", "DOWNLOAD_COMPLETE", {"duration_seconds": 150})
        await asyncio.sleep(1)
        
        # 3. Transcribe
        await event_store.insert_event(session_id, "Whisper", "CHUNK_TRANSCRIBED", {"chunk": 1, "text": "Hello AI World!"})
        await asyncio.sleep(1)
        
        # 4. Finish
        await event_store.insert_event(session_id, "System", "PIPELINE_COMPLETE", {"status": "success"})


@router.post("/ingest/audio")
@limiter.limit("5/minute")
async def start_audio_ingestion(
    request: Request,
    payload: AudioIngestRequest,
    background_tasks: BackgroundTasks,
    # يمكننا استدعاء event_store للاستخدام اللحظي هنا، لكن لا نمرره للمهمة الخلفية
    event_store: EventStoreRepository = Depends(get_event_store)
):
    """
    يبدأ عملية معالجة فيديو يوتيوب في الخلفية.
    """
    session_id = f"sess_{payload.lesson_id}"
    
    # تمرير الـ Pool للمهمة الطويلة لتفتح اتصالها الخاص
    background_tasks.add_task(
        run_pipeline_task_dummy, 
        payload.youtube_url, 
        payload.lesson_id, 
        request.app.state.db_pool
    )
    
    return {
        "status": "processing_started",
        "session_id": session_id,
        "message": "Subscribe to /ingest/events/{session_id} to track live progress."
    }


@router.get("/ingest/events/{session_id}")
async def stream_ingestion_events(
    request: Request,
    session_id: str,
    event_store: EventStoreRepository = Depends(get_event_store)
):
    """
    مسار SSE (Server-Sent Events) يبث تقدم المعالجة للمستخدم مباشرة.
    """
    async def event_generator():
        last_event_count = 0
        
        while True:
            # 🚨 2026 Best Practice: فحص انفصال العميل لإنهاء الـ Loop وتوفير الموارد
            if await request.is_disconnected():
                print(f"🔌 Client disconnected from stream: {session_id}")
                break
                
            events = await event_store.get_session_events(session_id)
            
            # إذا ظهرت أحداث جديدة، نقوم ببثها
            if len(events) > last_event_count:
                new_events = events[last_event_count:]
                for event in new_events:
                    # بناء هيكل SSE متوافق مع معايير الـ Frontend
                    yield {
                        "event": event["event_type"],
                        "data": str(event["payload"])
                    }
                last_event_count = len(events)
                
                # إيقاف الـ Stream عند اكتمال أو فشل الـ Pipeline
                if any(e["event_type"] in ["PIPELINE_COMPLETE", "PIPELINE_FAILED"] for e in new_events):
                    break
            
            # Polling Rate (ثانية واحدة)
            await asyncio.sleep(1)

    return EventSourceResponse(event_generator())
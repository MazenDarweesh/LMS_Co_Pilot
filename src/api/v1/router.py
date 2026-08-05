import asyncio
from fastapi import APIRouter, BackgroundTasks, Request, Depends
from sse_starlette.sse import EventSourceResponse
from pydantic import BaseModel

from src.models.schemas import (
    AudioTranscriptionRequest, AudioTranscriptionResponse,
    RAGQueryRequest, RAGQueryResponse, AudioIngestRequest
)
from src.services.rag_service import rag_service

from src.core.middleware import limiter
from src.api.dependencies import get_event_store
from src.db.event_store import EventStoreRepository
from src.services.pipeline_orchestrator import pipeline_orchestrator

router = APIRouter(prefix="/v1", tags=["V1 API"])



@router.post("/query-rag", response_model=RAGQueryResponse)
async def query_rag(request: RAGQueryRequest):
    return await rag_service.query_rag(request.query, request.limit)


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
        pipeline_orchestrator.run_audio_pipeline, 
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
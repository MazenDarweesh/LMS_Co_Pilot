import asyncio
from fastapi import APIRouter, BackgroundTasks, Request, Depends
from sse_starlette.sse import EventSourceResponse
from pydantic import BaseModel

from src.models.schemas import (
    AudioTranscriptionRequest, AudioTranscriptionResponse,
    RAGQueryRequest, RAGQueryResponse, AudioIngestRequest, LessonMetadata
)
from src.models.search_models import SearchRequest, SearchResponse

class AudioIngestRequestV2(BaseModel):
    youtube_url:     str
    lesson_id:       str
    lesson_metadata: LessonMetadata | None = None
from src.services.rag_service import rag_service
from src.services.search_service import search_service

from src.core.middleware import limiter
from src.api.dependencies import get_event_store
from src.db.event_store import EventStoreRepository
from src.services.pipeline_orchestrator import pipeline_orchestrator

router = APIRouter(prefix="/v1", tags=["V1 API"])


@router.post("/query-rag", response_model=RAGQueryResponse)
async def query_rag(request: RAGQueryRequest):
    """Legacy endpoint — delegates to the real SearchService now."""
    return await rag_service.query_rag(request.query, request.limit)


@router.post("/search", response_model=SearchResponse)
async def search(req: SearchRequest):
    """
    🔍 Hybrid RAG Search — Week 8.
    Temporarily uses test entities (no auth) for development.
    Will require JWT (Authorization: Bearer <token>) after Week 7.
    """
    # TODO (Week 7): Replace with real user_entities from get_current_user dependency
    test_entities = [
        "tenant:default_company",
        "role:Admin",
        "role:Student",
    ]
    return await search_service.search(req, user_entities=test_entities)


@router.post("/ingest/audio")
@limiter.limit("5/minute")
async def start_audio_ingestion(
    request: Request,
    payload: AudioIngestRequestV2,
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
        request.app.state.db_pool,
        payload.lesson_metadata
    )
    
    return {
        "status": "processing_started",
        "session_id": session_id,
        "message": f"Track via /v1/ingest/events/{session_id}"
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

import os
import json
import glob
from pathlib import Path
from fastapi import HTTPException

CHECKPOINT_DIR = Path("downloads/checkpoints")

@router.get("/lessons/{lesson_id}")
async def get_lesson_result(lesson_id: str):
    """
    يقوم بجمع كل المقاطع (Chunks) الخاصة بدرس معين من نقاط الحفظ (Checkpoints)
    ويدمجها بالترتيب ليعرض النتيجة النهائية للدرس كاملاً.
    """
    # البحث عن كل ملفات الـ JSON الخاصة بهذا الدرس
    pattern = os.path.join(CHECKPOINT_DIR, f"{lesson_id}_chunk_*.json")
    chunk_files = glob.glob(pattern)
    
    if not chunk_files:
        raise HTTPException(status_code=404, detail=f"No processed data found for lesson: {lesson_id}. It might be still processing or failed.")
        
    merged_segments = []
    
    for file_path in chunk_files:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                merged_segments.append(data)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error reading checkpoint {file_path}: {str(e)}")
            
    # ترتيب المقاطع بناءً على وقت البداية لضمان تسلسل الدرس بشكل صحيح
    merged_segments.sort(key=lambda x: x.get("start_time", 0))
    
    return {
        "lesson_id": lesson_id,
        "total_chunks": len(merged_segments),
        "total_duration_seconds": sum(seg.get("end_time", 0) - seg.get("start_time", 0) for seg in merged_segments),
        "segments": merged_segments
    }
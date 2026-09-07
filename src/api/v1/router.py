import asyncio
import glob
import json
import os
import re
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request, status
from sse_starlette.sse import EventSourceResponse
import structlog

from src.api.dependencies import get_event_store
from src.core.config import settings
from src.core.middleware import limiter
from src.db.event_store import EventStoreRepository
from src.models.schemas import (
    AudioIngestRequestV2,
    GeneratedQuiz,
    GeneratedSummary,
    LessonMetadata,
    WebhookPayload,
)
from src.models.search_models import SearchRequest, SearchResponse
from src.services.auth_service import UserContext, get_current_user, require_role
from src.services.lesson_content_service import lesson_content_service
from src.services.lms_client import lms_client_service
from src.services.pipeline_orchestrator import pipeline_orchestrator
from src.services.qdrant_service import qdrant_service
from src.services.search_service import search_service

# Initialize Logger
logger = structlog.get_logger()

# Initialize Router
router = APIRouter(prefix="/v1", tags=["V1 API"])

# Constants
CHECKPOINT_DIR = Path("downloads/checkpoints")


@router.post("/search", response_model=SearchResponse)
@limiter.limit("30/minute")
async def search(
    request: Request,
    req: SearchRequest,
    user_ctx: UserContext = Depends(get_current_user)
):
    """
    🔍 Hybrid RAG Search
    Fully protected by JWT & precise Role/Level filtering.
    """
    # We pass the entire UserContext to enable precise Qdrant filtering
    return await search_service.search(req, user_ctx=user_ctx)


@router.post("/ingest/audio")
@limiter.limit("5/minute")
async def start_audio_ingestion(
    request: Request,
    payload: AudioIngestRequestV2,
    background_tasks: BackgroundTasks,
    event_store: EventStoreRepository = Depends(get_event_store),
    admin_ctx: UserContext = Depends(require_role("Admin"))
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


@router.post("/webhooks/lesson-updated", status_code=status.HTTP_202_ACCEPTED)
@limiter.limit("10/minute")
async def unified_lesson_webhook(
    request: Request,
    payload: WebhookPayload,
    background_tasks: BackgroundTasks,
    x_service_token: str = Header(..., alias="X-Service-Token")
):
    """
    مسار Webhook موحد يستقبل إشعارات التحديث أو الحذف من سيرفر الـ .NET.
    محمي بـ Service Token لمنع الهجمات الخارجية.
    """
    if x_service_token != settings.SERVICE_TOKEN:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid service token")

    if payload.action == "Deleted":
        # 🗑️ مسح المتجهات من قاعدة البيانات فوراً
        background_tasks.add_task(qdrant_service.delete_by_lesson_id, payload.lessonId)
        return {"status": "accepted", "message": "Deletion triggered"}
        
    elif payload.action == "Updated":
        # 🔄 سحب تفاصيل الفيديو من LMS (Full Context) وبدء دورة Ingestion جديدة
        async def fetch_and_ingest():
            try:
                context = await lms_client_service.get_lesson_full_context(payload.lessonId)
                
                url = context.get("videoUrl")
                # Parse LMS metadata into our LessonMetadata format
                meta = LessonMetadata(
                    tenant_ids=context.get("tenantIds", context.get("TenantIds", ["default"])),
                    module_id=context.get("moduleId", context.get("ModuleId", "")),
                    unit_id=context.get("unitId", context.get("UnitId", "")),
                    level_id=context.get("levelId", context.get("LevelId", "")),
                    type_id=context.get("typeId", context.get("TypeId", "")),
                    lesson_id=payload.lessonId,
                    target_roles=context.get("targetRoles", context.get("TargetRoles", []))
                )

                # ✅ Fix: Delete old chunks FIRST before re-ingesting.
                # Prevents stale/duplicate vectors after a lesson content update.
                await qdrant_service.delete_by_lesson_id(payload.lessonId)
                logger.info("Old Qdrant chunks cleared before re-ingest", lesson_id=payload.lessonId)

                # Run the ingestion pipeline securely in the background
                await pipeline_orchestrator.run_audio_pipeline(
                    url, payload.lessonId, request.app.state.db_pool, meta
                )
            except Exception as e:
                print(f"❌ Webhook Ingestion Failed for {payload.lessonId}: {e}")
                
        background_tasks.add_task(fetch_and_ingest)
        return {"status": "accepted", "message": "Update and Ingestion triggered"}

    raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid action")


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


@router.get("/lessons/{lesson_id}")
# 🛡️ OWASP A04: Insecure Design (Rate Limiting to prevent DoS)
@limiter.limit("20/minute")
async def get_lesson_result(request: Request, lesson_id: str):
    """
    يقوم بجمع كل المقاطع (Chunks) الخاصة بدرس معين من نقاط الحفظ (Checkpoints)
    ويدمجها بالترتيب ليعرض النتيجة النهائية للدرس كاملاً.
    """
    # 🛡️ OWASP A01: Broken Access Control (Path Traversal Protection)
    if not re.match(r"^[a-zA-Z0-9_-]+$", lesson_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid lesson_id format. Potential path traversal attempt blocked."
        )
        
    # البحث عن كل ملفات الـ JSON الخاصة بهذا الدرس
    pattern = os.path.join(CHECKPOINT_DIR, f"{lesson_id}_chunk_*.json")
    chunk_files = glob.glob(pattern)
    
    if not chunk_files:
        raise HTTPException(
            status_code=404,
            detail=f"No processed data found for lesson: {lesson_id}. It might be still processing or failed."
        )
        
    merged_segments = []
    
    for file_path in chunk_files:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                merged_segments.append(data)
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Error reading checkpoint {file_path}: {str(e)}"
            )
            
    # ترتيب المقاطع بناءً على وقت البداية لضمان تسلسل الدرس بشكل صحيح
    merged_segments.sort(key=lambda x: x.get("start_time", 0))
    
    return {
        "lesson_id": lesson_id,
        "total_chunks": len(merged_segments),
        "total_duration_seconds": sum(seg.get("end_time", 0) - seg.get("start_time", 0) for seg in merged_segments),
        "segments": merged_segments
    }


# ---------------------------------------------------------------------------
# AI Content Generation (Admin Only) - PR-3 Stateless Implementation
# ---------------------------------------------------------------------------

@router.post("/admin/lessons/{lesson_id}/generate-quiz", response_model=GeneratedQuiz)
@limiter.limit("5/minute")
async def generate_lesson_quiz(
    request: Request,
    lesson_id: str,
    admin_ctx: UserContext = Depends(require_role("Admin"))
):
    """
    يقوم بتوليد اختبار (Quiz) للدرس عبر سحب المحتوى من Qdrant، ثم يعيد الـ JSON للـ LMS للحفظ.
    مخصص للـ Admins فقط.
    """
    try:
        # 🛡️ OWASP A01: Path Traversal Protection — same pattern as GET /lessons/{lesson_id}
        if not re.match(r"^[a-zA-Z0-9_-]+$", lesson_id):
            raise HTTPException(
                status_code=400,
                detail="Invalid lesson_id format. Potential path traversal attempt blocked."
            )
        # Generate exactly 5 questions across the timeline
        return await lesson_content_service.generate_quiz(lesson_id=lesson_id, num_questions=5)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail="فشل توليد الاختبار بسبب خطأ داخلي.")


@router.post("/admin/lessons/{lesson_id}/generate-summary", response_model=GeneratedSummary)
@limiter.limit("5/minute")
async def generate_lesson_summary(
    request: Request,
    lesson_id: str,
    admin_ctx: UserContext = Depends(require_role("Admin"))
):
    """
    يقوم بتوليد ملخص هيكلي للدرس عبر سحب المحتوى من Qdrant، ثم يعيد الـ JSON للـ LMS للحفظ.
    مخصص للـ Admins فقط.
    """
    try:
        # 🛡️ OWASP A01: Path Traversal Protection
        if not re.match(r"^[a-zA-Z0-9_-]+$", lesson_id):
            raise HTTPException(
                status_code=400,
                detail="Invalid lesson_id format. Potential path traversal attempt blocked."
            )
        return await lesson_content_service.generate_summary(lesson_id=lesson_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail="فشل توليد الملخص بسبب خطأ داخلي.")
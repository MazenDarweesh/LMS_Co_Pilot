import asyncio
import glob
import hashlib
import json
import os
import re
import time
from pathlib import Path

from cachetools import TTLCache
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sse_starlette.sse import EventSourceResponse
import structlog

from src.api.dependencies import get_event_store
from src.core.config import settings
from src.core.metrics import record_search_feedback
from src.core.middleware import limiter
from src.db.event_store import EventStoreRepository
from qdrant_client.models import Filter, FieldCondition, MatchValue
from src.models.schemas import (
    AudioIngestRequestV2,
    GeneratedQuiz,
    GeneratedSummary,
    LessonMetadata,
    WebhookPayload,
    SyncFailedRequest,
    SyncFailedResponse,
    LessonStatusResponse,
    extract_video_id,
    LessonReferenceRequest,
    LessonReferenceResponse,
)
from typing import Literal
from src.models.search_models import (
    SearchRequest,
    SearchResponse,
    FeedbackRequest,
    FeedbackResponse,
    FeedbackRating,
    AdminFeedbackResponse,
    FeedbackItemResponse,
    FeedbackAnalyticsResponse,
)
from src.models.auth_models import LessonFullContext
from src.services.auth_service import UserContext, get_current_user, require_role, verify_webhook_signature
from src.services.lesson_content_service import lesson_content_service

from src.services.lms_client import lms_client_service
from src.services.pipeline_orchestrator import pipeline_orchestrator
from src.services.qdrant_service import qdrant_service
from src.services.search_service import search_service
from src.services.semantic_cache_service import semantic_cache_service
from src.services.exact_cache_service import exact_cache_service
from src.services.feedback_service import feedback_service

# Initialize Logger
logger = structlog.get_logger()

# Initialize Base Router (endpoints decorated on base_router)
base_router = APIRouter()
router = base_router

# Constants
CHECKPOINT_DIR = Path("downloads/checkpoints")
# Whitelist of SourceItem fields safe for JSONB storage (prevents leaking unknown client fields)
_SOURCE_FIELDS: frozenset[str] = frozenset({"type", "url", "title", "start", "end", "page", "section", "lesson_id"})


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


# In-memory deduplication cache for feedback (24h TTL)
_feedback_cache: TTLCache[str, bool] = TTLCache(maxsize=10_000, ttl=86400)


@router.post("/search/stream")
@limiter.limit("30/minute")
async def search_stream_endpoint(
    request: Request,
    req: SearchRequest,
    user_ctx: UserContext = Depends(get_current_user),
) -> StreamingResponse:
    """
    ⚡ Real-time Token Streaming Search via Server-Sent Events (SSE).
    - Emits sources event first for instant video citation rendering.
    - Streams tokens with heartbeat pings (: heartbeat\n\n) to defeat proxy timeouts.
    - Listens for client disconnects to abort upstream token generation immediately.
    """
    return StreamingResponse(
        search_service.search_stream(req, user_ctx, request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/search/feedback", response_model=FeedbackResponse)
@limiter.limit("30/minute")
async def search_feedback_endpoint(
    request: Request,
    req: FeedbackRequest,
    background_tasks: BackgroundTasks,
    user_ctx: UserContext = Depends(get_current_user),
) -> FeedbackResponse:
    """
    💬 Student Feedback Endpoint (Thumbs Up / Down).
    - Deduplicates repeat votes on the exact answer via in-memory TTLCache (24 hours).
    - Persists feedback to PostgreSQL asynchronously via BackgroundTasks (Zero Latency <15ms).
    - Records Prometheus counter and emits structured audit logs for offline RAG quality optimization.
    """
    # Deduplicate repeat submissions on the exact same answer.
    # query_hash is ALWAYS computed server-side — any client-supplied value is ignored
    # to prevent crafted hashes from bypassing the UPSERT unique constraint.
    query_hash = hashlib.sha256(f"{req.query}:{req.lesson_id or ''}".encode("utf-8")).hexdigest()
    answer_hash = hashlib.sha256(req.answer.strip().encode("utf-8")).hexdigest()
    dedup_key = f"{user_ctx.user_id}:{query_hash}:{answer_hash}"

    if _feedback_cache.get(dedup_key) == req.rating.value:
        logger.info(
            "Duplicate student feedback ignored",
            user_id=user_ctx.user_id,
            query_hash=query_hash,
            answer_hash=answer_hash,
        )
        return FeedbackResponse(
            status="duplicate",
            message="تم تسجيل تقييمك مسبقاً بهذا الخيار لهذا السؤال. شكراً لمشاركتك! 🎓",
        )

    _feedback_cache[dedup_key] = req.rating.value
    record_search_feedback(req.rating.value)

    sources_dicts = [
        s.model_dump(include=_SOURCE_FIELDS)
        for s in req.sources[:5]
    ] if req.sources else []

    # Non-blocking async background persistence
    background_tasks.add_task(
        feedback_service.save_feedback,
        tenant_id=user_ctx.tenant_id,
        user_id=user_ctx.user_id,
        user_role=user_ctx.role,
        query=req.query,
        answer=req.answer,
        rating=req.rating.value,
        query_hash=query_hash,
        answer_hash=answer_hash,
        comment=req.comment,
        lesson_id=req.lesson_id,
        thread_id=req.thread_id,
        department_id=user_ctx.claims.department_id,
        sources=sources_dicts,
    )

    logger.info(
        "Student search feedback recorded 💬",
        user_id=user_ctx.user_id,
        tenant_id=user_ctx.tenant_id,
        rating=req.rating.value,
        lesson_id=req.lesson_id,
        thread_id=req.thread_id,
        query_snippet=req.query[:50],
        has_comment=bool(req.comment),
    )
    return FeedbackResponse()


@router.get("/admin/feedback")
@limiter.limit("60/minute")
async def get_admin_feedback(
    request: Request,
    lesson_id: str | None = None,
    rating: FeedbackRating | None = None,
    format: Literal["json", "ragas"] = "json",
    limit: int = Query(50, ge=1, le=200, description="عدد السجلات لكل صفحة (1-200)"),
    offset: int = Query(0, ge=0, description="رقم السجل الأول للصفحة الحالية"),
    admin_ctx: UserContext = Depends(require_role("Admin", "Teacher")),
):
    """
    📊 Admin & Teacher Feedback Analytics Endpoint.
    - Scoped strictly by the administrator's tenant_id (Company ID).
    - Supports filtering by lesson_id and rating (UP / DOWN).
    - If format='ragas', returns an evaluation dataset array ready for Ragas automated tests.
    """
    if format == "ragas":
        return await feedback_service.export_for_ragas(
            tenant_id=admin_ctx.tenant_id,
            lesson_id=lesson_id,
            limit=limit,
        )

    records = await feedback_service.get_tenant_feedback(
        tenant_id=admin_ctx.tenant_id,
        lesson_id=lesson_id,
        rating=rating.value if rating else None,
        limit=limit,
        offset=offset,
    )

    analytics = await feedback_service.get_feedback_analytics(
        tenant_id=admin_ctx.tenant_id,
        lesson_id=lesson_id,
    )

    formatted_records = [
        FeedbackItemResponse(
            id=r["id"],
            tenant_id=r["tenant_id"],
            department_id=r.get("department_id"),
            user_id=r["user_id"],
            user_role=r.get("user_role", "Student"),
            lesson_id=r.get("lesson_id"),
            thread_id=r.get("thread_id"),
            query_hash=r["query_hash"],
            answer_hash=r["answer_hash"],
            query_text=r["query_text"],
            answer_text=r["answer_text"],
            rating=FeedbackRating(r["rating"]),
            comment=r.get("comment"),
            sources=r.get("sources") or [],
            created_at=str(r["created_at"]) if r.get("created_at") else None,
        )
        for r in records
    ]

    return AdminFeedbackResponse(
        records=formatted_records,
        analytics=FeedbackAnalyticsResponse(
            total_votes=analytics["total_votes"],
            up_votes=analytics["up_votes"],
            down_votes=analytics["down_votes"],
            satisfaction_rate=analytics["satisfaction_rate"],
        ),
        limit=limit,
        offset=offset,
    )


@router.post("/admin/cache/clear")
@limiter.limit("10/minute")
async def clear_all_caches(
    request: Request,
    admin_ctx: UserContext = Depends(require_role("Admin"))
):
    """
    🧹 Purges both Tier-1 Exact Cache (In-Memory) and Tier-2 Semantic Cache (Qdrant Vector Cache).
    Allows Admins and Developers to flush stale or incorrect cached responses.
    """
    from src.services.exact_cache_service import exact_cache_service
    from src.services.semantic_cache_service import semantic_cache_service

    exact_cache_service.clear()
    await semantic_cache_service.clear()

    logger.info("All caches purged by admin", admin_user_id=admin_ctx.user_id)
    return {
        "status": "success",
        "message": "تم تفريغ كافة مستويات الكاش (Exact Cache + Semantic Cache) بنجاح ✅",
    }


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


@router.post(
    "/webhooks/lesson-updated",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(verify_webhook_signature)],
)
@limiter.limit("60/minute")
async def unified_lesson_webhook(
    request: Request,
    payload: WebhookPayload,
    background_tasks: BackgroundTasks,
):
    """
    مسار Webhook موحد يستقبل إشعارات التحديث أو الحذف من سيرفر الـ .NET.
    محمي بتوقيع رقمي HMAC-SHA256 قياسي مع حماية ضد هجمات الإعادة (Anti-Replay).
    يدعم أيضاً التوافق العكسي مع X-Service-Token القديم لمنع انقطاع الخدمة (Zero-Downtime).
    """
    action_norm = payload.action.strip().lower()
    lesson_id = payload.lesson_id

    if action_norm == "deleted":
        # 🗑️ مسح المتجهات والكاش من قاعدة البيانات فوراً
        lms_client_service.invalidate_lesson_context(lesson_id)
        background_tasks.add_task(qdrant_service.delete_by_lesson_id, lesson_id)
        background_tasks.add_task(semantic_cache_service.invalidate_by_lesson_id, lesson_id)
        background_tasks.add_task(exact_cache_service.invalidate_by_lesson_id, lesson_id)
        return {"status": "accepted", "message": "Deletion triggered"}
        
    elif action_norm == "updated":
        # 🔄 الترتيب الصارم: 1. إبطال الكاش الدلالي -> 2. إبطال الكاش الفوري -> 3. مسح Qdrant -> 4. إعادة الـ Ingestion
        lms_client_service.invalidate_lesson_context(lesson_id)
        background_tasks.add_task(
            sync_and_reingest_lesson,
            lesson_id,
            request.app.state.db_pool,
        )
        return {"status": "accepted", "message": "Update and Ingestion triggered"}

    elif action_norm in ("referenced", "linked"):
        # 🔗 ربط درس جديد بمحتوى فيديو معالج مسبقاً (Process Once, Reference Everywhere)
        lms_client_service.invalidate_lesson_context(lesson_id)
        video_url = payload.video_url
        module_id = payload.module_id
        unit_id = payload.unit_id

        if not video_url:
            # Fallback: محاولة جلب سياق الدرس من LMS إذا لم يتضمنه الـ payload
            try:
                raw_ctx = await lms_client_service.get_lesson_full_context(lesson_id)
                video_url = raw_ctx.video_url
                module_id = module_id or raw_ctx.module_id
                unit_id = unit_id or raw_ctx.unit_id
            except Exception as e:
                logger.warning("Could not fetch full context for reference linking", lesson_id=lesson_id, error=str(e))

        if not video_url:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "video_url is required for referencing existing content")

        clean_vid = extract_video_id(video_url)
        linked = await qdrant_service.link_lesson_to_existing_video(
            video_identifier=clean_vid,
            source_url=video_url,
            new_lesson_id=lesson_id,
            new_module_id=module_id,
            new_unit_id=unit_id,
        )

        if linked > 0:
            # 🔔 إشعار سيرفر الـ .NET فوراً باكتمال المعالجة في 0 ثانية
            background_tasks.add_task(
                lms_client_service.notify_lesson_ai_status,
                lesson_id=lesson_id,
                status="Completed",
                total_chunks=linked,
            )
            return {
                "status": "accepted",
                "message": f"Lesson successfully linked to {linked} existing chunks (Process Once)",
                "linked_chunks": linked,
            }
        else:
            # المحتوى لم تتم معالجته مسبقاً بعد؛ جدولة معالجة كاملة عبر البايبلاين
            background_tasks.add_task(
                sync_and_reingest_lesson,
                lesson_id,
                request.app.state.db_pool,
            )
            return {
                "status": "accepted",
                "message": "Content not yet indexed; queued full ingestion",
                "linked_chunks": 0,
            }

    raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Invalid action: '{payload.action}'")


@router.post(
    "/admin/lessons/reference",
    response_model=LessonReferenceResponse,
    status_code=status.HTTP_200_OK,
)
@limiter.limit("60/minute")
async def link_lesson_reference(
    request: Request,
    payload: LessonReferenceRequest,
    background_tasks: BackgroundTasks,
    admin_ctx: UserContext = Depends(require_role("Admin")),
):
    """
    يربط درساً أو موديولاً جديداً بمحتوى فيديو تمت معالجته مسبقاً في Qdrant.
    ينفذ مبدأ 'Process Once, Reference Everywhere' في < 10ms دون إعادة التضمين أو التفريغ.
    """
    clean_vid = extract_video_id(payload.source_video_url)
    linked = await qdrant_service.link_lesson_to_existing_video(
        video_identifier=clean_vid,
        source_url=payload.source_video_url,
        new_lesson_id=payload.lesson_id,
        new_module_id=payload.module_id,
        new_unit_id=payload.unit_id,
    )

    if linked > 0:
        background_tasks.add_task(
            lms_client_service.notify_lesson_ai_status,
            lesson_id=payload.lesson_id,
            status="Completed",
            total_chunks=linked,
        )
        return LessonReferenceResponse(
            status="success",
            message=f"Successfully linked lesson {payload.lesson_id} to {linked} existing video chunks",
            points_linked=linked,
            video_id=clean_vid,
            lesson_id=payload.lesson_id,
            module_id=payload.module_id,
        )

    raise HTTPException(
        status.HTTP_404_NOT_FOUND,
        f"No existing chunks found in Qdrant for video: {payload.source_video_url}. Ingest the original lesson first."
    )



# ⚠️ ARCHITECTURAL CONSTRAINT:
# This in-memory lock is scoped to a single-replica deployment (current Phase 1 / MVP).
# If scaling horizontally to multi-pod (replicas > 1), migrate to a distributed lock
# (PostgreSQL lease table or Redis lock) as documented in docs/production_notes.md (ADR-09).
_ingest_locks: dict[str, asyncio.Lock] = {}
_ingest_locks_last_used: dict[str, float] = {}
_ingest_locks_guard = asyncio.Lock()
_INGEST_LOCK_MAX = 10_000
_INGEST_LOCK_IDLE_PRUNE_SECONDS = 3600  # 1 hour grace period to prevent TOCTOU race conditions


async def _get_lesson_ingest_lock(lesson_id: str) -> asyncio.Lock:
    """
    Thread-safe acquisition of a per-lesson lock with bounded memory pruning.
    Protects against TOCTOU race conditions by requiring locks to be both unlocked
    AND idle (> 1 hour) before eligible for pruning.
    Pruning evicts oldest-idle locks first and updates both structures atomically.
    """
    async with _ingest_locks_guard:
        now = time.monotonic()
        if lesson_id not in _ingest_locks:
            if len(_ingest_locks) >= _INGEST_LOCK_MAX:
                # Prune only locks that are unlocked AND idle > 1 hour
                stale_keys = [
                    k for k, ts in _ingest_locks_last_used.items()
                    if (now - ts) > _INGEST_LOCK_IDLE_PRUNE_SECONDS
                    and not _ingest_locks[k].locked()
                ]
                # Evict oldest idle entries first
                stale_keys.sort(key=lambda k: _ingest_locks_last_used.get(k, 0.0))
                for k in stale_keys:
                    _ingest_locks.pop(k, None)
                    _ingest_locks_last_used.pop(k, None)
                    if len(_ingest_locks) < 8000:
                        break
            _ingest_locks[lesson_id] = asyncio.Lock()

        _ingest_locks_last_used[lesson_id] = now
        return _ingest_locks[lesson_id]


async def sync_and_reingest_lesson(lesson_id: str, db_pool) -> None:
    """
    الترتيب الحتمي والصارم لعملية تحديث أو إعادة مزامنة درس مع قفل تزامني (Per-Lesson Lock):
    1. اكتساب قفل مخصص للدرس لمنع التنافس (Race Condition).
    2. إبطال الكاش الدلالي (Semantic Cache Invalidation).
    3. إبطال الكاش اللحظي (Exact LRU Cache Invalidation).
    4. حذف المتجهات القديمة من Qdrant لمنع الازدواجية والتسريب.
    5. جلب سياق الدرس من LMS وإعادة تشغيل مسار المعالجة الصوتية.
    """
    lock = await _get_lesson_ingest_lock(lesson_id)
    async with lock:
        try:
            # 1. إبطال الكاش الدلالي فوراً
            await semantic_cache_service.invalidate_by_lesson_id(lesson_id)

            # 2. إبطال الكاش الفوري
            exact_cache_service.invalidate_by_lesson_id(lesson_id)

            # 3. مسح المتجهات القديمة من Qdrant قبل إعادة المعالجة
            await qdrant_service.delete_by_lesson_id(lesson_id)
            logger.info("Caches and old Qdrant chunks cleared in strict order", lesson_id=lesson_id)

            # 4. جلب سياق الدرس وتشغيل الـ Ingestion
            raw_context = await lms_client_service.get_lesson_full_context(lesson_id)
            context = raw_context if isinstance(raw_context, LessonFullContext) else LessonFullContext.model_validate(raw_context)
            url = context.video_url or ""
            meta = LessonMetadata(
                tenant_ids=context.tenant_ids or ["default"],
                module_id=context.module_id,
                unit_id=context.unit_id,
                level_id=context.level_id,
                type_id=context.type_id,
                lesson_id=lesson_id,
                target_roles=context.target_roles,
            )

            await pipeline_orchestrator.run_audio_pipeline(
                url, lesson_id, db_pool, meta
            )
            logger.info("Sync and re-ingestion finished successfully", lesson_id=lesson_id)
        except Exception as e:
            logger.error("Sync and re-ingestion failed for lesson", lesson_id=lesson_id, error=str(e))
            asyncio.create_task(lms_client_service.notify_lesson_ai_status(
                lesson_id=lesson_id,
                status="Failed",
                error=str(e)
            ))


@router.post("/admin/sync-failed", response_model=SyncFailedResponse, status_code=status.HTTP_202_ACCEPTED)
@limiter.limit("5/minute")
async def trigger_sync_failed(
    request: Request,
    payload: SyncFailedRequest,
    background_tasks: BackgroundTasks,
    admin_ctx: UserContext = Depends(require_role("Admin"))
):
    """
    مسار إداري للتعافي من فشل الـ Webhooks وإعادة مزامنة الدروس المتأخرة أثناء الـ Downtime.
    مخصص للـ Admins فقط، ويطبق الترتيب الحتمي للتطهير وإعادة الـ Ingestion.
    """
    sanitized_ids: list[str] = []
    for lid in payload.lesson_ids:
        clean_lid = lid.strip()
        if not re.match(r"^[a-zA-Z0-9_-]+$", clean_lid):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid lesson_id format: '{clean_lid}'"
            )
        sanitized_ids.append(clean_lid)

    for lid in sanitized_ids:
        background_tasks.add_task(
            sync_and_reingest_lesson,
            lid,
            request.app.state.db_pool,
        )

    logger.info("Scheduled sync-failed reconciliation", count=len(sanitized_ids), admin_id=admin_ctx.user_id)
    return SyncFailedResponse(
        status="accepted",
        lessons_queued=sanitized_ids,
        count=len(sanitized_ids),
        message="Reconciliation and re-ingestion scheduled successfully"
    )


@router.get("/ingest/events/{session_id}")
@limiter.limit("20/minute")
async def stream_ingestion_events(
    request: Request,
    session_id: str,
    event_store: EventStoreRepository = Depends(get_event_store)
):
    """
    مسار SSE (Server-Sent Events) يبث تقدم المعالجة للمستخدم مباشرة.
    """
    # 🛡️ OWASP A01: Input Validation / Path Traversal & Injection Protection
    if not re.match(r"^[a-zA-Z0-9_-]+$", session_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid session_id format. Potential injection attempt blocked."
        )

    async def event_generator():
        last_event_count = 0
        
        while True:
            # 🚨 2026 Best Practice: فحص انفصال العميل لإنهاء الـ Loop وتوفير الموارد
            if await request.is_disconnected():
                logger.info("Client disconnected from SSE stream", session_id=session_id)
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


@router.get("/ingest/status/{lesson_id}", response_model=LessonStatusResponse)
@limiter.limit("60/minute")
async def get_ingest_status(
    request: Request,
    lesson_id: str
):
    """
    استعلام خفيف وفوري عن حالة معالجة الدرس:
    - يفحص عدد الـ Chunks المخزنة في Qdrant
    - يفحص آخر الأحداث المسجلة في الـ Event Store
    - يحدد هل يمكن توليد الكويز والملخص
    """
    if not re.match(r"^[a-zA-Z0-9_-]+$", lesson_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid lesson_id format. Potential injection attempt blocked."
        )

    # 1. فحص Qdrant لمعرفة عدد الـ Chunks الفعلي المخزن
    chunks_count = 0
    if getattr(qdrant_service, "_client", None) is not None:
        try:
            lesson_filter = Filter(
                must=[FieldCondition(key="lesson_id", match=MatchValue(value=lesson_id))]
            )
            records = await qdrant_service.client.scroll(
                collection_name=settings.QDRANT_COLLECTION,
                scroll_filter=lesson_filter,
                limit=100,
                with_payload=False
            )
            chunks_count = len(records[0]) if records and records[0] else 0
        except Exception as e:
            logger.warning("Could not scroll Qdrant for lesson status", lesson_id=lesson_id, error=str(e))

    # 2. فحص الـ Event Store لمعرفة الجلسة وآخر حدث
    session_id = f"sess_{lesson_id}"
    events = []
    pool = getattr(request.app.state, "db_pool", None)
    if pool is not None:
        try:
            async with pool.acquire() as conn:
                repo = EventStoreRepository(conn)
                events = await repo.get_session_events(session_id)
        except Exception as e:
            logger.warning("Could not fetch session events for lesson status", session_id=session_id, error=str(e))

    last_event = events[-1] if events else None
    last_event_type = last_event.get("event_type") if last_event else None
    last_updated = last_event.get("timestamp") if last_event else None
    error_msg = None

    # 3. تحديد الحالة المنطقية الحتمية
    if chunks_count > 0:
        status_val = "completed"
        can_generate = True
    elif last_event_type == "PIPELINE_FAILED":
        status_val = "failed"
        can_generate = False
        payload = last_event.get("payload", {})
        error_msg = payload.get("error") if isinstance(payload, dict) else str(payload)
    elif last_event_type == "PIPELINE_COMPLETE":
        status_val = "completed"
        can_generate = True
    elif last_event_type is not None:
        status_val = "processing"
        can_generate = False
    else:
        status_val = "idle"
        can_generate = False

    return LessonStatusResponse(
        lesson_id=lesson_id,
        status=status_val,
        chunks_count=chunks_count,
        current_stage=last_event_type,
        error=error_msg,
        can_generate_quiz=can_generate,
        can_generate_summary=can_generate,
        last_updated=last_updated
    )


@router.get("/lessons/{lesson_id}")
# 🛡️ OWASP A04: Insecure Design (Rate Limiting to prevent DoS)
@limiter.limit("20/minute")
async def get_lesson_result(
    request: Request,
    lesson_id: str,
    user_ctx: UserContext = Depends(get_current_user),
):
    """
    يقوم بجمع كل المقاطع (Chunks) الخاصة بدرس معين من نقاط الحفظ (Checkpoints)
    ويدمجها بالترتيب ليعرض النتيجة النهائية للدرس كاملاً.
    محمي بالكامل ضد ثغرة BOLA (OWASP API Security Top 1).
    """
    # 🛡️ OWASP A01: Broken Access Control (Path Traversal Protection)
    if not re.match(r"^[a-zA-Z0-9_-]+$", lesson_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid lesson_id format. Potential path traversal attempt blocked."
        )

    # 🛡️ OWASP A01: Broken Object Level Authorization (BOLA) Check
    if user_ctx.claims.role != "Admin":
        # For students, strictly verify lesson entitlement
        if (
            not user_ctx.permissions
            or not user_ctx.permissions.accessible_lesson_ids
            or lesson_id not in user_ctx.permissions.accessible_lesson_ids
        ):
            logger.warning(
                "BOLA access blocked: user unauthorized for lesson checkpoints",
                lesson_id=lesson_id,
                user_id=user_ctx.user_id,
                company_id=user_ctx.company_id,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: You do not have permission to view this lesson."
            )
    else:
        # Cross-Tenant Protection for Admin: Verify lesson belongs to admin's organization (Fail-Closed)
        try:
            raw_context = await lms_client_service.get_lesson_full_context(lesson_id)
            context = raw_context if isinstance(raw_context, LessonFullContext) else LessonFullContext.model_validate(raw_context)
            lesson_tenants = context.tenant_ids
            
            # Fail-Closed: A lesson with no associated organization cannot be accessed
            if not lesson_tenants:
                logger.warning(
                    "Lesson without organization rejected for admin access",
                    lesson_id=lesson_id,
                    admin_id=user_ctx.user_id,
                )
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Access denied: Lesson is not associated with any organization."
                )

            if user_ctx.company_id not in lesson_tenants:
                logger.warning(
                    "Cross-tenant admin access blocked for lesson checkpoints",
                    lesson_id=lesson_id,
                    admin_id=user_ctx.user_id,
                    admin_company=user_ctx.company_id,
                    lesson_tenants=lesson_tenants,
                )
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Access denied: This lesson does not belong to your organization."
                )
        except HTTPException:
            raise
        except Exception as e:
            logger.warning(
                "Cross-tenant check FAILED - rejecting admin access (Fail-Closed)",
                lesson_id=lesson_id,
                admin_id=user_ctx.user_id,
                error=str(e),
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Unable to verify lesson organization ownership. Please try again later."
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
@limiter.limit("10/minute")
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
        logger.warning("Quiz generation ValueError", lesson_id=lesson_id, error=str(e))
        if "لا يوجد محتوى" in str(e):
            raise HTTPException(
                status_code=404,
                detail=f"No transcribed chunks found for lesson '{lesson_id}'. Please process the video first."
            )
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("Quiz generation failed", lesson_id=lesson_id, error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail=f"فشل توليد الاختبار بسبب خطأ داخلي: {str(e)}")


@router.post("/admin/lessons/{lesson_id}/generate-summary", response_model=GeneratedSummary)
@limiter.limit("10/minute")
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
        logger.warning("Summary generation ValueError", lesson_id=lesson_id, error=str(e))
        if "لا يوجد محتوى" in str(e):
            raise HTTPException(
                status_code=404,
                detail=f"No transcribed chunks found for lesson '{lesson_id}'. Please process the video first."
            )
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("Summary generation failed", lesson_id=lesson_id, error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail=f"فشل توليد الملخص بسبب خطأ داخلي: {str(e)}")


# ---------------------------------------------------------------------------
# Route Prefix Multiplexing (Dual-Prefix Support for Postel's Law / .NET Compat)
# ---------------------------------------------------------------------------
# 1. Primary V1 Router (/v1/...)
v1_router = APIRouter(prefix="/v1", tags=["V1 API"])
v1_router.include_router(base_router)

# 2. .NET Compatibility Router (/api/...) — guarantees zero 404s when .NET calls /api/...
api_compat_router = APIRouter(prefix="/api", tags=["API Compat (.NET)"])
api_compat_router.include_router(base_router)

# Default export for backwards compatibility with existing imports:
router = v1_router
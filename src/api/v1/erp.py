import json
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import structlog

from src.core.middleware import limiter
from src.models.erp_models import (
    AgentGoalRequest,
    ControlRolesRequest,
    ControlRolesResponse,
    LeftoverRequest,
    LeftoverResponse,
    NavFeedbackRequest,
    NavRequest,
    NavResolution,
    TelemetryBatchRequest,
)
from src.models.mcp_chat_models import ErpChatStreamRequest
from sse_starlette.sse import EventSourceResponse
from src.services.erp_copilot import (
    agentic_stepper_service,
    append_session_event,
    erp_decision_memory_service,
    erp_service,
)
from src.services.erp_copilot.mcp.chat_service import unified_chat_service
from src.services.shared_infrastructure import (
    UserContext,
    get_current_user,
    get_optional_user,
)

logger = structlog.get_logger()

router = APIRouter(prefix="/v1/erp", tags=["ERP Assistant"])


@router.post(
    "/navigation/resolve",
    response_model=NavResolution,
    status_code=status.HTTP_200_OK,
    summary="Resolve ERP Navigation Destination & Intent",
)
@limiter.limit("60/minute")
async def resolve_erp_navigation(
    request: Request,
    payload: NavRequest,
    user: UserContext | None = Depends(get_optional_user),
) -> NavResolution:
    """
    🔍 الموجّه الذكي لشاشات الـ ERP (AI-only):
    - تحديد نية المستخدم (سؤال / تنقل / إجراء) واختيار الشاشة من القائمة الحية المرسلة فقط.
    - الاستعانة بذاكرة القرارات المؤكدة (Qdrant) لتجاوز الـ LLM عند التطابق.
    - تقييم عتبات القرار (go / ask / clarify) وحظر الهلوسة في المعرفات.
    """
    logger.info(
        "Received ERP navigation request",
        candidates_count=len(payload.candidates),
        msg_len=len(payload.user_message),
        current_path=payload.current_path,
        tenant_known=user is not None,
    )
    return await erp_service.resolve_navigation(
        payload,
        tenant_id=user.tenant_id if user else None,
        user_id=user.user_id if user else None,
    )


@router.post(
    "/navigation/feedback",
    status_code=status.HTTP_200_OK,
    summary="Confirm or reject a routing decision (feeds the decision memory)",
)
@limiter.limit("120/minute")
async def feedback_erp_navigation(
    request: Request,
    payload: NavFeedbackRequest,
    user: UserContext = Depends(get_current_user),
) -> dict[str, str]:
    """applied → القرار يُحفظ في الذاكرة الدلالية. rejected → يُحذف ويُسجل في التدقيق."""
    found = await erp_decision_memory_service.apply_feedback(
        tenant_id=user.tenant_id, decision_id=payload.decision_id, outcome=payload.outcome
    )
    return {"status": "recorded" if found else "ignored"}


@router.post(
    "/controls/resolve",
    response_model=ControlRolesResponse,
    status_code=status.HTTP_200_OK,
    summary="Resolve functional roles (add_row / new_form) of on-screen buttons",
)
@limiter.limit("60/minute")
async def resolve_erp_controls(
    request: Request,
    payload: ControlRolesRequest,
    user: UserContext | None = Depends(get_optional_user),
) -> ControlRolesResponse:
    """🔘 يحدد الذكاء الاصطناعي الزر المسؤول عن إضافة سطر وعن بدء مستند جديد من الأزرار الظاهرة فقط."""
    return await erp_service.resolve_controls(
        payload,
        tenant_id=user.tenant_id if user else None,
        user_id=user.user_id if user else None,
    )


@router.post(
    "/form-fill/resolve-leftover",
    response_model=LeftoverResponse,
    status_code=status.HTTP_200_OK,
    summary="Resolve Leftover Cascading Form Fields",
)
@limiter.limit("60/minute")
async def resolve_erp_leftover_fields(
    request: Request,
    payload: LeftoverRequest,
) -> LeftoverResponse:
    """
    📝 التعبئة الذكية التتابعية للحقول الجديدة:
    - فحص الحقول الجديدة التي ظهرت ديناميكياً بعد اختيار المستخدم.
    - مطابقة القيم المستخرجة مسبقاً وتجاهل الحقول المعطلة (disabled).
    - التحقق الصارم من الخيارات (options)؛ وفي حال عدم التطابق تُحال لسؤال المستخدم (ask_user).
    """
    logger.info(
        "Received ERP leftover form fill request",
        new_fields_count=len(payload.new_fields),
        extracted_keys_count=len(payload.extracted_data),
    )
    return await erp_service.resolve_leftover(payload)


@router.post(
    "/telemetry",
    status_code=status.HTTP_200_OK,
    summary="Record ERP Live Session Telemetry Events (Unified Blackbox)",
)
@limiter.limit("300/minute")
async def record_erp_telemetry(
    request: Request,
    payload: TelemetryBatchRequest,
) -> dict:
    """
    📦 الصندوق الأسود الموحد لكل جلسة ERP:
    - استقبال أحداث التشغيل الميداني من الكوبيلوت في المتصفح.
    - تفويض الكتابة إلى session_telemetry.append_session_event بصيغة JSONL موحدة.
    """
    if not payload.events:
        return {"status": "empty", "written": 0}

    for ev in payload.events:
        details_dict = dict(ev.details) if ev.details else {}
        if ev.duration_ms is not None and "durationMs" not in details_dict:
            details_dict["durationMs"] = ev.duration_ms

        raw_stage = ev.stage.strip().upper()
        stage_name = (
            raw_stage
            if raw_stage.startswith(("BROWSER.", "STEPPER.", "CDP."))
            else f"BROWSER.{raw_stage}"
        )

        append_session_event(
            session_id=payload.session_id,
            level=ev.level,
            stage=stage_name,
            message=ev.event,
            details=details_dict,
            trace_id=ev.trace_id or payload.trace_id,
            screen_key=payload.screen_key,
            timestamp=ev.timestamp,
        )

    return {
        "status": "recorded",
        "session_id": payload.session_id,
        "written": len(payload.events),
    }


@router.post("/agent/stream", summary="تشغيل العميل البصري المستقل مع بث خطوات التنفيذ الحية عبر SSE")
async def stream_agent_execution(req: AgentGoalRequest):
    """
    يشغل حلقة الأتمتة البصرية المستقلة (Path 2) عبر بروتوكول CDP.
    يبث خطوات الرصد والتحليل البصري والتنفيذ لحظياً للواجهة عبر Server-Sent Events.
    """
    async def event_generator():
        async for step_update in agentic_stepper_service.execute_goal_stream(
            goal=req.goal,
            cdp_port=req.cdp_port,
            cdp_host=req.cdp_host,
            session_id=req.session_id,
            max_steps=req.max_steps,
        ):
            yield {
                "event": "step",
                "data": json.dumps(step_update, ensure_ascii=False)
            }

    return EventSourceResponse(event_generator())


@router.post(
    "/chat/stream",
    summary="Unified General Chat + LMS Search + ERP Navigation SSE Stream",
)
@limiter.limit("30/minute")
async def stream_erp_general_chat(
    request: Request,
    payload: ErpChatStreamRequest,
    user: UserContext | None = Depends(get_optional_user),
) -> EventSourceResponse:
    """
    💬 المساعد الموحد العام (General Chat + LMS RAG + ERP Navigation):
    - يجيب عن الأسئلة العامة باللهجة المصرية أو العربية الفصحى مثل Claude/GPT.
    - يبحث في دروس المنصة (search_lms_lessons) ويبث حدث `sources`.
    - يوجه لشاشات الـ ERP (navigate_erp_screen) ويبث حدث `nav_action`.
    - يلتزم بالصدق عند تعطيل MCP (`MCP_ENABLED=False`) دون اختلاق أي أرقام حية.
    """
    async def event_generator():
        async for event in unified_chat_service.stream_chat(
            payload,
            user=user,
            request=request,
        ):
            yield {
                "event": event["event"],
                "data": json.dumps(event["data"], ensure_ascii=False),
            }

    return EventSourceResponse(
        event_generator(),
        ping=15,
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )



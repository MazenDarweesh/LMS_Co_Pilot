import json
import re
from pathlib import Path
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
from sse_starlette.sse import EventSourceResponse
from src.services.erp_copilot import (
    agentic_stepper_service,
    erp_decision_memory_service,
    erp_service,
)
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


ERP_LOGS_DIR = Path("logs/erp_sessions")
SHARED_LOGS_DIR = Path("e:/Mazen/shared_logs/erp_sessions")


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
    - كتابة الأحداث في ملف الجلسة الموحد (session_<session_id>.log).
    - مشاركة السجل بين المشاريع في مجلد logs/erp_sessions.
    """
    if not payload.events:
        return {"status": "empty", "written": 0}

    clean_id = re.sub(r"[^a-zA-Z0-9_\-]", "_", payload.session_id)
    filename = f"session_{clean_id}.log"

    targets = [ERP_LOGS_DIR]
    try:
        SHARED_LOGS_DIR.mkdir(parents=True, exist_ok=True)
        targets.append(SHARED_LOGS_DIR)
    except Exception:
        pass

    ERP_LOGS_DIR.mkdir(parents=True, exist_ok=True)

    formatted_lines = []
    for ev in payload.events:
        details_str = json.dumps(ev.details, ensure_ascii=False) if ev.details else ""
        screen_tag = f"[{payload.screen_key}] " if payload.screen_key else ""
        line = f"[{ev.timestamp}] [{ev.level.upper()}] [{ev.stage.upper()}] {screen_tag}{ev.event} | {details_str}\n"
        formatted_lines.append(line)

    payload_text = "".join(formatted_lines)

    for target_dir in targets:
        try:
            file_path = target_dir / filename
            with open(file_path, "a", encoding="utf-8") as f:
                f.write(payload_text)
        except Exception as e:
            logger.warn("Failed to write erp telemetry to path", path=str(target_dir), error=str(e))

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



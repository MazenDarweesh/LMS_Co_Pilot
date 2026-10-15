from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import structlog

from src.core.middleware import limiter
from src.models.erp_models import (
    ControlRolesRequest,
    ControlRolesResponse,
    LeftoverRequest,
    LeftoverResponse,
    NavFeedbackRequest,
    NavRequest,
    NavResolution,
)
from src.services.auth_service import UserContext, get_current_user, get_optional_user
from src.services.erp_decision_memory_service import erp_decision_memory_service
from src.services.erp_service import erp_service

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

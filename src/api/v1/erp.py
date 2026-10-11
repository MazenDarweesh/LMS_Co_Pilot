from fastapi import APIRouter, Request, status
import structlog

from src.core.middleware import limiter
from src.models.erp_models import (
    LeftoverRequest,
    LeftoverResponse,
    NavRequest,
    NavResolution,
)
from src.services.erp_service import erp_service

logger = structlog.get_logger()

router = APIRouter(prefix="/v1/erp", tags=["ERP Assistant"])


@router.post(
    "/navigation/resolve",
    response_model=NavResolution,
    status_code=status.HTTP_200_OK,
    summary="Resolve ERP Navigation Destination",
)
@limiter.limit("60/minute")
async def resolve_erp_navigation(
    request: Request,
    payload: NavRequest,
) -> NavResolution:
    """
    🔍 الملاحة الذكية وحل التباس شاشات الـ ERP:
    - استقبال طلب المستخدم وقائمة الشاشات المرشحة المعروضة.
    - ترتيب الشاشات باستخدام التطابق المعجمي ثم إعادة الترتيب بالـ LLM.
    - تقييم عتبات القرار (go للتوجيه المباشر، ask للتخيير، clarify للتوضيح).
    - حظر الهلوسة وقصر المخرجات على أعلى 3 مرشحين من القائمة المتاحة فقط.
    """
    logger.info(
        "Received ERP navigation request",
        candidates_count=len(payload.candidates),
        msg_len=len(payload.user_message),
        current_path=payload.current_path,
    )
    return await erp_service.resolve_navigation(payload)


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

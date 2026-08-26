from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from typing import Dict, Any

from src.utils.arabic_speech_utils import calculate_wer_cer, tafqit_arabic
from src.services.auth_service import require_role, UserContext
from src.core.middleware import limiter

router = APIRouter(prefix="/v1/speech", tags=["Speech AI Utilities"])

class EvaluationRequest(BaseModel):
    reference_text: str
    hypothesis_text: str
    apply_normalization: bool = True

@router.post("/evaluate-quality", response_model=Dict[str, Any])
@limiter.limit("10/minute")
async def evaluate_transcription_quality(
    request: Request,
    payload: EvaluationRequest,
    admin_ctx: UserContext = Depends(require_role("Admin"))
):
    """
    يقوم بحساب معدلات الخطأ (WER/CER) بين النص الأصلي المرجعي (Reference)
    والنص الذي ولّده الذكاء الاصطناعي (Hypothesis).
    مفيد جداً في صفحة "تقييم جودة الـ AI" في الـ Dashboard الخاصة بالمشرفين.
    """
    result = calculate_wer_cer(
        reference=payload.reference_text,
        hypothesis=payload.hypothesis_text,
        normalize=payload.apply_normalization
    )
    return {
        "status": "success",
        "evaluation": result,
        "quality_flag": "🔴 Review Needed" if result["wer"] > 0.25 else "✅ Good"
    }

class TafqitRequest(BaseModel):
    number: int

@router.post("/tafqit", response_model=Dict[str, str])
@limiter.limit("20/minute")
async def convert_number_to_words(request: Request, payload: TafqitRequest):
    """
    يحول الأرقام الرياضية إلى نص عربي فصيح (تفقيط).
    مفيد لتجهيز الأرقام المحاسبية لمحركات الـ TTS للوكيل الصوتي التفاعلي.
    """
    words = tafqit_arabic(payload.number)
    return {
        "number": str(payload.number),
        "arabic_words": words
    }

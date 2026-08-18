from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Dict, Any

from src.utils.arabic_speech_utils import calculate_wer_cer, tafqit_arabic
from src.services.auth_service import require_role, UserContext

router = APIRouter(prefix="/v1/speech", tags=["Speech AI Utilities"])

class EvaluationRequest(BaseModel):
    reference_text: str
    hypothesis_text: str
    apply_normalization: bool = True

@router.post("/evaluate-quality", response_model=Dict[str, Any])
async def evaluate_transcription_quality(
    request: EvaluationRequest,
    admin_ctx: UserContext = Depends(require_role("Admin"))
):
    """
    يقوم بحساب معدلات الخطأ (WER/CER) بين النص الأصلي المرجعي (Reference)
    والنص الذي ولّده الذكاء الاصطناعي (Hypothesis).
    مفيد جداً في صفحة "تقييم جودة الـ AI" في الـ Dashboard الخاصة بالمشرفين.
    """
    result = calculate_wer_cer(
        reference=request.reference_text,
        hypothesis=request.hypothesis_text,
        normalize=request.apply_normalization
    )
    return {
        "status": "success",
        "evaluation": result,
        "quality_flag": "🔴 Review Needed" if result["wer"] > 0.25 else "✅ Good"
    }

class TafqitRequest(BaseModel):
    number: int

@router.post("/tafqit", response_model=Dict[str, str])
async def convert_number_to_words(request: TafqitRequest):
    """
    يحول الأرقام الرياضية إلى نص عربي فصيح (تفقيط).
    مفيد لتجهيز الأرقام المحاسبية لمحركات الـ TTS للوكيل الصوتي التفاعلي.
    """
    words = tafqit_arabic(request.number)
    return {
        "number": str(request.number),
        "arabic_words": words
    }

from src.core.prompts import get_erp_navigation_prompt
import asyncio
import json
import re
from typing import Any
import structlog
from google import genai
from google.genai import types

from src.core.config import settings
from src.models.erp_models import (
    FieldSignatureIn,
    LeftoverRequest,
    LeftoverResponse,
    NavCandidateIn,
    NavRequest,
    NavResolution,
    NavScored,
)
from src.utils.arabic_speech_utils import normalize_arabic_text_leaderboard

logger = structlog.get_logger()


def _stem_arabic_token(token: str) -> str:
    """استخراج تقريبي لجذر أو بادئة الكلمة العربية لمطابقة الجمع والمثنى والزوائد"""
    t = normalize_arabic_text_leaderboard(token).strip()
    if not t:
        return ""
    # إزالة أل التعريف
    if t.startswith("ال") and len(t) > 3:
        t = t[2:]
    # إزالة لواحق الجمع والمثنى الشائعة (ين، ون، ات، ية، ه)
    for suffix in ("ين", "ون", "ات", "ية", "ة", "ه"):
        if t.endswith(suffix) and len(t) > len(suffix) + 2:
            t = t[:-len(suffix)]
            break
    return t


def _compute_lexical_similarity(user_text: str, label: str, path: list[str]) -> float:
    """
    حساب درجة التطابق المعجمي واللفظي بين رسالة المستخدم وعنوان ومسار الشاشة.
    يُرجع درجة بين 0.0 و 0.95.
    """
    user_norm = normalize_arabic_text_leaderboard(user_text)
    full_cand_text = f"{label} {' '.join(path)}"
    cand_norm = normalize_arabic_text_leaderboard(full_cand_text)

    if not user_norm or not cand_norm:
        return 0.0

    # تطابق تام أو احتواء صريح لاسم الشاشة
    label_norm = normalize_arabic_text_leaderboard(label)
    if label_norm and (label_norm in user_norm or user_norm in label_norm):
        return 0.90

    user_tokens = [w for w in user_norm.split() if len(w) > 1]
    cand_tokens = [w for w in cand_norm.split() if len(w) > 1]

    if not user_tokens or not cand_tokens:
        return 0.0

    user_stems = {_stem_arabic_token(w) for w in user_tokens if len(_stem_arabic_token(w)) > 1}
    cand_stems = {_stem_arabic_token(w) for w in cand_tokens if len(_stem_arabic_token(w)) > 1}

    common_stems = user_stems.intersection(cand_stems)
    if not common_stems:
        # فحص احتواء مقطعي للكلمات
        has_partial = False
        for u in user_stems:
            for c in cand_stems:
                if (u in c or c in u) and min(len(u), len(c)) >= 3:
                    has_partial = True
                    break
            if has_partial:
                break
        return 0.35 if has_partial else 0.05

    overlap_score = len(common_stems) / max(1, len(cand_stems))
    # تقييم الثقة المعجمية
    confidence = min(0.85, 0.40 + (overlap_score * 0.45))
    return round(confidence, 2)


class ErpService:
    """
    خدمة مساعد الـ ERP الموحدة — Singleton Service:
    1. Navigation Intent Resolver (Lexical + LLM Structured Rerank).
    2. Progressive Form-Fill Leftover Resolver.
    """

    def __init__(self) -> None:
        self._gemini_client: genai.Client | None = None

    def initialize(self) -> None:
        """تهيئة الخدمة وربط عميل Gemini عند بدء تشغيل الـ FastAPI Lifespan"""
        try:
            self._gemini_client = genai.Client(api_key=settings.GEMINI_API_KEY)
            logger.info("ERP Service initialized successfully ✅")
        except Exception as e:
            logger.error("Failed to initialize Gemini Client in ErpService", error=str(e))
            self._gemini_client = None

    async def resolve_navigation(self, req: NavRequest) -> NavResolution:
        """
        ترتيب الشاشات المرشحة واختيار القرار المناسب (go, ask, clarify)
        وفقاً للعتبات المعرفة بالسيرفر.
        """
        user_msg = req.user_message.strip()
        candidates_map = {c.id: c for c in req.candidates}
        total_candidates = len(req.candidates)

        logger.info(
            "ERP Navigation resolve requested",
            query_len=len(user_msg),
            candidates_count=total_candidates,
            current_path=req.current_path,
        )

        # 0. Fast-Path Gating: إذا كان الاستعلام استفساراً معرفياً أو سؤالاً نظرياً بحتاً بدون أمر تنقل صريح
        sanitized_msg = re.sub(r'\b(كمية|كميات|بكمية)\b', '', user_msg)
        question_patterns = [
            r'\bما الذي\b', r'\bماذا\b', r'\bما هو\b', r'\bما هي\b', r'\bماهو\b', r'\bماهي\b',
            r'\bما الفرق\b', r'\bكيف\b', r'\bلماذا\b', r'\bاشرح\b', r'\bوضح\b', r'\bهل\b',
            r'\bأين\b', r'\bاين\b', r'\bمتى\b', r'\bكم\b', r'\bليه\b', r'\bازاي\b', r'\bإزاي\b',
            r'\bطريقة عمل\b', r'\bآلية عمل\b', r'\bممكن تفهمني\b', r'\bعرفني\b'
        ]
        is_question = any(re.search(pat, sanitized_msg) for pat in question_patterns)

        explicit_nav_markers = (
            "افتح", "روح", "وديني", "انتقل", "شاشة", "صفحة", "حولني", "وجهني",
            "ادخل على", "عايز أسجل", "سجل لي", "سجل", "اعمل", "أنشئ", "انشئ",
            "فاتورة مشتريات", "فاتورة مبيعات", "قيد يومية", "تسجيل عميل", "تسوية جردية", "محضر جرد"
        )
        has_nav_cmd = any(m in user_msg for m in explicit_nav_markers)

        if is_question and not has_nav_cmd:
            logger.info("Fast-path bypass: Query is purely educational/question, returning clarify", query=user_msg)
            return NavResolution(decision="clarify", candidates=[])

        # 1. حساب الدرجات المعجمية (Lexical Baseline) كـ Fallback سريع
        lexical_scores: dict[str, float] = {}
        for c in req.candidates:
            lexical_scores[c.id] = _compute_lexical_similarity(user_msg, c.label, c.path)

        scored_candidates: list[NavScored] = []
        llm_succeeded = False

        # 2. محاولة استدعاء الـ LLM Reranker إذا كان عميل Gemini مهيأ
        if self._gemini_client:
            try:
                candidates_payload = [
                    {"id": c.id, "label": c.label, "path": c.path}
                    for c in req.candidates
                ]

                prompt = get_erp_navigation_prompt(
                    user_msg=user_msg,
                    current_path_json=json.dumps(req.current_path, ensure_ascii=False),
                    candidates_json=json.dumps(candidates_payload, ensure_ascii=False, indent=2),
                )

                resp = await asyncio.wait_for(
                    asyncio.to_thread(
                        self._gemini_client.models.generate_content,
                        model=settings.GEMINI_MODEL,
                        contents=prompt,
                        config=types.GenerateContentConfig(
                            response_mime_type="application/json",
                            temperature=0.0,
                        ),
                    ),
                    timeout=12.0,
                )

                raw_text = resp.text if hasattr(resp, "text") and resp.text else ""
                parsed = json.loads(raw_text)

                if isinstance(parsed, list):
                    for item in parsed:
                        if not isinstance(item, dict):
                            continue
                        c_id = str(item.get("id", "")).strip()
                        # Strict validation: منع الهلوسة في الـ id
                        if c_id not in candidates_map:
                            continue
                        try:
                            conf = float(item.get("confidence", 0.0))
                            conf = max(0.0, min(1.0, conf))
                        except (ValueError, TypeError):
                            conf = 0.0
                        reason = str(item.get("reason", "")).strip() or "مطابقة دلالية بناءً على محتوى الشاشة"
                        scored_candidates.append(NavScored(id=c_id, confidence=conf, reason=reason))
                    if scored_candidates:
                        llm_succeeded = True
            except Exception as e:
                logger.warning(
                    "LLM Navigation rerank failed or timed out, falling back to lexical scoring",
                    error=str(e),
                )

        # 3. Fallback إلى الـ Lexical Scoring في حال فشل الـ LLM أو عدم تغطيته
        if not llm_succeeded or not scored_candidates:
            scored_candidates = []
            for c in req.candidates:
                score = lexical_scores.get(c.id, 0.0)
                reason = "مطابقة معجمية للألفاظ والمسار" if score > 0.2 else "مطابقة معجمية منخفضة"
                scored_candidates.append(NavScored(id=c.id, confidence=score, reason=reason))

        # 4. تصفية صارمة وترتيب النتائج
        # التحقق من أن كل id ينتمي حصراً للمرشحات المدخلة
        valid_scored = [s for s in scored_candidates if s.id in candidates_map]
        # إزالة التكرارات إن وُجدت مع الاحتفاظ بأعلى درجة
        unique_scored: dict[str, NavScored] = {}
        for s in valid_scored:
            if s.id not in unique_scored or s.confidence > unique_scored[s.id].confidence:
                unique_scored[s.id] = s

        sorted_candidates = sorted(unique_scored.values(), key=lambda x: x.confidence, reverse=True)

        # اقتطاع القائمة لأعلى 3 مرشحين فقط
        top_candidates = sorted_candidates[:3]

        # 5. تطبيق منطق اتخاذ القرار الصارم
        go_threshold = settings.ERP_NAV_GO_THRESHOLD
        gap_threshold = settings.ERP_NAV_GAP_THRESHOLD
        clarify_threshold = settings.ERP_NAV_CLARIFY_THRESHOLD

        if not top_candidates:
            decision = "clarify"
        else:
            top1 = top_candidates[0]
            top2_conf = top_candidates[1].confidence if len(top_candidates) > 1 else 0.0
            gap = round(top1.confidence - top2_conf, 4)

            if top1.confidence >= go_threshold and gap >= gap_threshold:
                decision = "go"
            elif top1.confidence < clarify_threshold:
                decision = "clarify"
            else:
                decision = "ask"

        logger.info(
            "ERP Navigation decision resolved",
            decision=decision,
            top1_id=top_candidates[0].id if top_candidates else None,
            top1_conf=top_candidates[0].confidence if top_candidates else 0.0,
        )

        return NavResolution(decision=decision, candidates=top_candidates)

    async def resolve_leftover(self, req: LeftoverRequest) -> LeftoverResponse:
        """
        حل وتعبئة الحقول الجديدة التي ظهرت ديناميكياً (Leftover Form Fill)
        بناءً على البيانات المستخرجة وخيارات الحقول المتاحة.
        """
        logger.info(
            "ERP Leftover resolve requested",
            new_fields_count=len(req.new_fields),
            extracted_keys=list(req.extracted_data.keys()),
            filled_keys=list(req.filled.keys()),
        )

        fields_res: dict[str, Any] = {}
        ask_user_res: list[str] = []

        # تجاهل الحقول المعطلة (disabled) وتجهيز الحقول الصالحة
        active_fields = [f for f in req.new_fields if not f.disabled]
        active_keys = {f.key for f in active_fields}

        # تجهيز خريطة للبيانات المستخرجة لتسهيل المطابقة (Exact, Lowercase, Normalized Label)
        norm_extracted: dict[str, Any] = {}
        for k, v in req.extracted_data.items():
            if v is not None:
                norm_extracted[k] = v
                norm_extracted[k.lower()] = v
                norm_extracted[normalize_arabic_text_leaderboard(str(k))] = v

        for field in active_fields:
            matched_val: Any = None
            field_key_norm = normalize_arabic_text_leaderboard(field.key)
            field_label_norm = normalize_arabic_text_leaderboard(field.label)

            # البحث عن القيمة في البيانات المستخرجة
            if field.key in req.extracted_data:
                matched_val = req.extracted_data[field.key]
            elif field.key.lower() in norm_extracted:
                matched_val = norm_extracted[field.key.lower()]
            elif field.label in req.extracted_data:
                matched_val = req.extracted_data[field.label]
            elif field_label_norm in norm_extracted:
                matched_val = norm_extracted[field_label_norm]
            elif field_key_norm in norm_extracted:
                matched_val = norm_extracted[field_key_norm]

            # فحص خيارات الحقل (options) إن وجدت
            if field.options and len(field.options) > 0:
                if matched_val is not None:
                    str_val = str(matched_val).strip()
                    matched_opt: str | None = None
                    norm_val = normalize_arabic_text_leaderboard(str_val)

                    # المطابقة الحرفية أو المعجمية مع الخيارات المتاحة
                    for opt in field.options:
                        if str_val.lower() == opt.lower() or norm_val == normalize_arabic_text_leaderboard(opt):
                            matched_opt = opt
                            break

                    if matched_opt is not None:
                        fields_res[field.key] = matched_opt
                    else:
                        # القيمة لا تطابق الخيارات المتاحة حرفياً -> توضع في ask_user
                        ask_user_res.append(field.key)
                else:
                    # لم يُذكر له قيمة واضحة في البيانات المستخرجة
                    pass
            else:
                # حقل عادي بدون خيارات مقيدة
                if matched_val is not None:
                    fields_res[field.key] = matched_val

        # ضمان أن جميع المفاتيح في fields و ask_user تنتمي حصراً لمفاتيح new_fields النشطة
        final_fields = {k: v for k, v in fields_res.items() if k in active_keys}
        final_ask_user = [k for k in ask_user_res if k in active_keys and k not in final_fields]

        return LeftoverResponse(fields=final_fields, ask_user=final_ask_user)


erp_service = ErpService()

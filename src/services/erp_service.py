from src.core.prompts import get_erp_control_roles_prompt, get_erp_navigation_prompt
import asyncio
import json
import re
from typing import Any
import structlog
from google import genai
from google.genai import types

from src.core.config import settings
from src.models.erp_models import (
    ControlRolesRequest,
    ControlRolesResponse,
    FieldSignatureIn,
    LeftoverRequest,
    LeftoverResponse,
    NavCandidateIn,
    NavRequest,
    NavResolution,
    NavScored,
)
from src.services.erp_decision_memory_service import (
    candidate_fingerprint,
    erp_decision_memory_service,
    navigation_fingerprint,
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

    async def _generate_json(self, prompt: str, timeout: float = 12.0) -> Any:
        """Single Gemini JSON call shared by every ERP routing prompt (DRY)."""
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
            timeout=timeout,
        )
        raw_text = resp.text if hasattr(resp, "text") and resp.text else ""
        return json.loads(raw_text)

    @staticmethod
    def _parse_router_output(
        parsed: Any, candidates_map: dict[str, NavCandidateIn]
    ) -> tuple[str, list[NavScored]]:
        """Parses the AI router output (object with intent, or legacy list) with strict id validation."""
        intent = "unknown"
        items: Any = parsed
        if isinstance(parsed, dict):
            raw_intent = str(parsed.get("intent", "")).strip().lower()
            intent = raw_intent if raw_intent in ("question", "navigate", "action") else "unknown"
            items = parsed.get("candidates", [])

        scored: list[NavScored] = []
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            c_id = str(item.get("id", "")).strip()
            # Strict validation: منع الهلوسة في الـ id
            if c_id not in candidates_map:
                continue
            try:
                conf = max(0.0, min(1.0, float(item.get("confidence", 0.0))))
            except (ValueError, TypeError):
                conf = 0.0
            reason = str(item.get("reason", "")).strip() or "مطابقة دلالية بناءً على محتوى الشاشة"
            scored.append(NavScored(id=c_id, confidence=conf, reason=reason))

        if intent == "question":
            scored = [s.model_copy(update={"confidence": 0.0}) for s in scored]
        elif intent == "action":
            # Demote secondary details/report screens so they never hijack transactional entry
            for i, s in enumerate(scored):
                s_lower = s.id.lower()
                if any(kw in s_lower for kw in ("details", "detail", "تقرير", "report", "تفاصيل", "استعلام", "inquiry")):
                    scored[i] = s.model_copy(update={"confidence": min(s.confidence, 0.15)})
        return intent, scored

    @staticmethod
    def _decide(top_candidates: list[NavScored]) -> str:
        """Applies the server-side go / ask / clarify thresholds."""
        if not top_candidates:
            return "clarify"
        top1 = top_candidates[0]
        top2_conf = top_candidates[1].confidence if len(top_candidates) > 1 else 0.0
        gap = round(top1.confidence - top2_conf, 4)
        if top1.confidence >= settings.ERP_NAV_GO_THRESHOLD and gap >= settings.ERP_NAV_GAP_THRESHOLD:
            return "go"
        if top1.confidence < settings.ERP_NAV_CLARIFY_THRESHOLD:
            return "clarify"
        return "ask"

    async def resolve_navigation(
        self,
        req: NavRequest,
        tenant_id: str | None = None,
        user_id: str | None = None,
    ) -> NavResolution:
        """
        ترتيب الشاشات المرشحة وتحديد نية المستخدم (سؤال / تنقل / إجراء) بالكامل عبر الذكاء الاصطناعي:
        0. ذاكرة القرارات المؤكدة (Qdrant) — تتجاوز استدعاء الـ LLM عند وجود تطابق دلالي موثّق.
        1. موجّه الذكاء الاصطناعي (قرار واحد: intent + درجات الشاشات).
        2. fallback معجمي فقط عند تعذر الـ LLM (بدون تخمين النية).
        """
        user_msg = req.user_message.strip()
        candidates_map = {c.id: c for c in req.candidates}

        logger.info(
            "ERP Navigation resolve requested",
            query_len=len(user_msg),
            candidates_count=len(req.candidates),
            current_path=req.current_path,
        )

        fingerprint = navigation_fingerprint(req.candidates)
        memory_active = bool(tenant_id and user_id) and erp_decision_memory_service.ready

        # 0. Verified-decision memory
        if memory_active:
            hit = await erp_decision_memory_service.lookup_navigation(user_msg, tenant_id, fingerprint)
            if hit is not None:
                remembered, matched_point_id = hit
                if all(c.id in candidates_map for c in remembered.candidates):
                    remembered.decision_id = await erp_decision_memory_service.record_navigation(
                        tenant_id, user_id, user_msg, fingerprint, remembered, matched_point_id
                    )
                    return remembered

        # 1. AI router
        intent = "unknown"
        scored_candidates: list[NavScored] = []
        source = "ai"
        if self._gemini_client:
            try:
                candidates_payload = [
                    {"id": c.id, "label": c.label, "path": c.path} for c in req.candidates
                ]
                prompt = get_erp_navigation_prompt(
                    user_msg=user_msg,
                    current_path_json=json.dumps(req.current_path, ensure_ascii=False),
                    candidates_json=json.dumps(candidates_payload, ensure_ascii=False, indent=2),
                )
                parsed = await self._generate_json(prompt, timeout=12.0)
                intent, scored_candidates = self._parse_router_output(parsed, candidates_map)
            except Exception as e:
                logger.warning(
                    "AI navigation router failed or timed out, falling back to lexical scoring",
                    error=str(e),
                )
                intent, scored_candidates = "unknown", []

        # 2. Lexical fallback (outage only): never guesses intent
        if not scored_candidates:
            source = "lexical"
            intent = "unknown"
            for c in req.candidates:
                score = _compute_lexical_similarity(user_msg, c.label, c.path)
                reason = "مطابقة معجمية للألفاظ والمسار" if score > 0.2 else "مطابقة معجمية منخفضة"
                scored_candidates.append(NavScored(id=c.id, confidence=score, reason=reason))

        # 3. Dedupe, penalize detail screens for action intent, sort, top-3
        unique_scored: dict[str, NavScored] = {}
        for s in scored_candidates:
            if intent == "action":
                cand_obj = candidates_map.get(s.id)
                label_lower = (cand_obj.label if cand_obj else s.id).lower()
                id_lower = s.id.lower()
                if any(k in id_lower or k in label_lower for k in ["detail", "تفاصيل", "report", "تقرير", "inquiry", "استعلام", "log"]):
                    s.confidence = 0.0
                    s.reason = "شاشة تفاصيل/تقرير غير صالحة لتسجيل أو إنشاء المعاملات"
            if s.id not in unique_scored or s.confidence > unique_scored[s.id].confidence:
                unique_scored[s.id] = s
        top_candidates = sorted(unique_scored.values(), key=lambda x: x.confidence, reverse=True)[:3]

        # 4. Decision
        if source == "ai" and intent == "question":
            resolution = NavResolution(decision="clarify", candidates=[], intent="question", source="ai")
        else:
            resolution = NavResolution(
                decision=self._decide(top_candidates),
                candidates=top_candidates,
                intent=intent,
                source=source,
            )

        logger.info(
            "ERP Navigation decision resolved",
            decision=resolution.decision,
            intent=resolution.intent,
            source=resolution.source,
            top1_id=top_candidates[0].id if top_candidates else None,
            top1_conf=top_candidates[0].confidence if top_candidates else 0.0,
        )

        if memory_active:
            resolution.decision_id = await erp_decision_memory_service.record_navigation(
                tenant_id, user_id, user_msg, fingerprint, resolution
            )
        return resolution

    async def resolve_controls(
        self,
        req: ControlRolesRequest,
        tenant_id: str | None = None,
        user_id: str | None = None,
    ) -> ControlRolesResponse:
        """
        يحدد الذكاء الاصطناعي دور أزرار الشاشة (add_row / new_form) من الأزرار الظاهرة فعلياً،
        ويُحفظ القرار في قاعدة البيانات (مفتاح: tenant + screen + بصمة تسميات الأزرار).
        """
        controls_by_id = {c.id: c for c in req.controls}
        fingerprint = candidate_fingerprint([("", c.label) for c in req.controls])
        memory_active = bool(tenant_id and user_id) and erp_decision_memory_service.ready

        def _ids_from_labels(roles_by_label: dict[str, str]) -> dict[str, str]:
            label_to_id: dict[str, str] = {}
            for c in req.controls:
                label_to_id.setdefault(c.label, c.id)
            return {r: label_to_id[lbl] for r, lbl in roles_by_label.items() if lbl in label_to_id}

        if memory_active:
            cached = await erp_decision_memory_service.lookup_controls(tenant_id, req.screen_id, fingerprint)
            if cached:
                roles = _ids_from_labels(cached)
                if roles:
                    return ControlRolesResponse(roles=roles, source="memory")

        if not self._gemini_client:
            logger.warning("Control roles requested but Gemini client is unavailable", screen_id=req.screen_id)
            return ControlRolesResponse(roles={}, source="ai")

        try:
            payload = [{"id": c.id, "label": c.label} for c in req.controls]
            prompt = get_erp_control_roles_prompt(
                screen_id=req.screen_id,
                controls_json=json.dumps(payload, ensure_ascii=False, indent=2),
            )
            parsed = await self._generate_json(prompt, timeout=12.0)
        except Exception as e:
            logger.warning("AI control roles resolution failed", error=str(e), screen_id=req.screen_id)
            return ControlRolesResponse(roles={}, source="ai")

        roles: dict[str, str] = {}
        if isinstance(parsed, dict):
            for role in ("add_row", "new_form"):
                btn_id = str(parsed.get(role) or "").strip()
                if btn_id in controls_by_id:  # strict anti-hallucination validation
                    roles[role] = btn_id

        if roles and memory_active:
            await erp_decision_memory_service.save_controls(
                tenant_id, user_id, req.screen_id, fingerprint,
                {r: controls_by_id[i].label for r, i in roles.items()},
            )
        return ControlRolesResponse(roles=roles, source="ai")

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

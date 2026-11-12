from src.core.prompts import (
    get_erp_control_roles_prompt,
    get_erp_leftover_resolution_prompt,
    get_erp_navigation_prompt,
)
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
from src.services.erp_copilot.erp_decision_memory_service import (
    candidate_fingerprint,
    erp_decision_memory_service,
    navigation_fingerprint,
)
from src.services.erp_copilot.forms_catalog_service import forms_catalog_service
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


BILINGUAL_SCREEN_MAP: dict[str, list[str]] = {
    "purchases": ["مشتريات", "شراء", "فاتورة مشتريات", "فاتوره مشتريات"],
    "sales": ["مبيعات", "بيع", "فاتورة مبيعات", "فاتوره مبيعات", "salesdetails"],
    "entry": ["قيد", "قيود", "يومية", "journal"],
    "productprocess": ["تحويل", "اذن", "صرف", "اضافة", "مخزن"],
    "suppliers": ["موردين", "مورد"],
    "customers": ["عملاء", "عميل"],
    "items": ["اصناف", "صنف", "منتجات", "منتج"],
}

DISQUALIFIED_ACTION_KEYWORDS: list[str] = [
    "total", "details", "detail", "report", "log", "inquiry",
    "setting", "settings", "setup", "config", "configuration",
    "اجمالي", "إجمالي", "تفاصيل", "تقرير", "استعلام", "ارصدة", "أرصدة",
    "إعدادات", "اعدادات", "تهيئة", "تهيئه", "انواع", "أنواع"
]

PRIMARY_OPERATIONAL_MODULES_NORM: frozenset[str] = frozenset(
    normalize_arabic_text_leaderboard(m)
    for m in (
        "الموردين و المشتريات",
        "العملاء  و المبيعات",
        "العملاء و المبيعات",
        "الحسابات العامه",
        "المخازن",
        "المرتبات",
        "التصنيع",
    )
)

SECONDARY_MODULES_NORM: frozenset[str] = frozenset(
    normalize_arabic_text_leaderboard(m)
    for m in (
        "الفاتورة الالكترونية",
        "الادارة العليا",
        "تقارير تكملية",
        "اعدادات",
        "اعدادات المرتبات",
        "الانظمة المتخصصة",
        "المراجعة والترحيل",
        "AdminPanel",
    )
)

CORE_PRIMARY_SCREEN_ALLOWLIST_NORM: frozenset[str] = frozenset(
    normalize_arabic_text_leaderboard(s)
    for s in (
        "فواتير المشتريات",
        "فواتير المبيعات",
        "المشتريات",
        "بيانات الموردين",
        "بيانات العملاء",
        "قيود اليومية",
        "القيد العام",
        "حركات المخازن",
        "اذن صرف",
        "اذن اضافة",
        "تحويلات المخازن",
        "طلب سلفة",
    )
)

SECONDARY_SCREEN_KEYWORDS_NORM: tuple[str, ...] = tuple(
    normalize_arabic_text_leaderboard(k)
    for k in (
        "المرحلة", "مرحل", "فلاحين", "البان", "مصمم", "تفاصيل",
        "تقرير", "استعلام", "اعدادات", "الكترونية", "انواع", "ارصدة", "ميزان",
    )
)

REPORT_INQUIRY_KEYWORDS_NORM: tuple[str, ...] = tuple(
    normalize_arabic_text_leaderboard(k)
    for k in ("تقرير", "تقارير", "كشف", "استعلام", "ميزان", "ارصدة", "تفاصيل")
)


def _is_report_or_inquiry_query(user_text: str) -> bool:
    u_norm = normalize_arabic_text_leaderboard(user_text)
    tokens = set(u_norm.split())
    return any(kw in tokens or kw in u_norm for kw in REPORT_INQUIRY_KEYWORDS_NORM)


def _is_ambiguous_invoice_query(user_text: str) -> bool:
    """True for generic plural invoice requests like 'عايز افتح شاشة الفواتير' without a domain qualifier."""
    u_norm = normalize_arabic_text_leaderboard(user_text)
    if not any(inv in u_norm for inv in ("فواتير", "فاتوره", "فاتورة")):
        return False
    qualifiers = tuple(
        normalize_arabic_text_leaderboard(q)
        for q in (
            "مبيعات", "مبيع", "مشتريات", "مشتري", "شراء", "بيع",
            "مرحلة", "مرحل", "فلاحين", "البان", "الكترونية", "مرتجع", "عرض سعر",
            "نقد", "اجل", "امر شراء",
        )
    )
    return not any(q in u_norm for q in qualifiers)


def _candidate_priority_tier(user_text: str, label: str, path: list[str]) -> tuple[int, bool]:
    """
    Ranks navigation candidates strictly by main/operational module paths and an explicit
    core-screen allowlist (never relying on numeric ID cutoffs).
    Returns (tier, is_core_allowlist) where:
      3 = core allowlist screen inside a primary operational module
      2 = primary operational module screen (or explicitly requested secondary keyword)
      1 = neutral module screen without unrequested secondary terms
      0 = unrequested secondary module or secondary report/specialty screen
    """
    u_norm = normalize_arabic_text_leaderboard(user_text)
    label_norm = normalize_arabic_text_leaderboard(label or "")
    path_norms = [normalize_arabic_text_leaderboard(p) for p in (path or []) if p]

    is_allowlist = label_norm in CORE_PRIMARY_SCREEN_ALLOWLIST_NORM
    is_primary_mod = any(p in PRIMARY_OPERATIONAL_MODULES_NORM for p in path_norms)
    is_secondary_mod = any(p in SECONDARY_MODULES_NORM for p in path_norms)

    cand_secondary_hits = [kw for kw in SECONDARY_SCREEN_KEYWORDS_NORM if kw and kw in label_norm]
    user_requested_secondary = any(
        (kw in u_norm) for kw in cand_secondary_hits
    ) or any((p in u_norm) for p in path_norms if p in SECONDARY_MODULES_NORM)

    if user_requested_secondary and cand_secondary_hits:
        return (2, is_allowlist)
    if (is_secondary_mod and not user_requested_secondary) or (cand_secondary_hits and not user_requested_secondary):
        return (0, is_allowlist)
    if is_primary_mod and is_allowlist:
        return (3, True)
    if is_primary_mod or is_allowlist:
        return (2, is_allowlist)
    return (1, False)


def _compute_lexical_similarity(user_text: str, label: str, path: list[str]) -> float:
    """
    حساب درجة التطابق المعجمي واللفظي بين رسالة المستخدم وعنوان ومسار الشاشة.
    يدعم المطابقة الثنائية (عربي/إنجليزي) واستبعاد شاشات التقارير للإجراءات، مع ترجيح الوحدات الرئيسية.
    """
    user_lower = user_text.lower()
    full_cand_text = f"{label} {' '.join(path)}".lower()
    is_report_query = _is_report_or_inquiry_query(user_text)
    tier, is_allowlist = _candidate_priority_tier(user_text, label, path)

    # فحص نية الإجراء لتصفير شاشات التقارير والإجماليات (ما لم يطلب المستخدم تقريراً صراحةً)
    is_action = not is_report_query and any(
        w in user_lower for w in ["سجل", "اضف", "أضف", "انشئ", "أنشئ", "فاتورة", "فاتوره", "قيد", "اذن", "إذن"]
    )
    if is_action:
        if any(bad in full_cand_text for bad in DISQUALIFIED_ACTION_KEYWORDS):
            return 0.0

    # طلبات الفواتير العامة الغامضة ("عايز افتح شاشة الفواتير"): نرفع فواتير البيع والشراء بالتساوي لتفعيل ask
    if _is_ambiguous_invoice_query(user_text):
        label_norm = normalize_arabic_text_leaderboard(label or "")
        if "فواتير" in label_norm or "فاتور" in label_norm:
            if tier >= 3:
                return 0.78
            if tier >= 2:
                return 0.58
            return 0.25 if tier == 0 else 0.45

    # مطابقة المصطلحات الثنائية (Bilingual domain matching) عند عدم طلب تقرير صريح
    has_invoice_intent = any(w in user_lower for w in ["فاتورة", "فاتوره", "سجل", "انشئ", "أنشئ", "دخل"])
    bilingual_bonus = 0.0
    if not is_report_query:
        for en_key, ar_terms in BILINGUAL_SCREEN_MAP.items():
            cand_matches_domain = en_key in full_cand_text or any(term in full_cand_text for term in ar_terms)
            if cand_matches_domain:
                for term in ar_terms:
                    if term in user_lower:
                        if has_invoice_intent and en_key in ("purchases", "sales", "entry", "productprocess"):
                            bilingual_bonus = max(bilingual_bonus, 0.96 if tier >= 2 else 0.48)
                        elif has_invoice_intent and en_key in ("suppliers", "customers"):
                            bilingual_bonus = max(bilingual_bonus, 0.55 if tier >= 2 else 0.30)
                        elif en_key in ("suppliers", "customers"):
                            if tier == 0:
                                bilingual_bonus = max(bilingual_bonus, 0.45)
                            elif is_allowlist:
                                bilingual_bonus = max(bilingual_bonus, 0.95)
                            else:
                                bilingual_bonus = max(bilingual_bonus, 0.65)
                        else:
                            bilingual_bonus = max(bilingual_bonus, 0.90 if tier >= 2 else 0.50)

    if bilingual_bonus > 0.0:
        return bilingual_bonus

    user_norm = normalize_arabic_text_leaderboard(user_text)
    cand_norm = normalize_arabic_text_leaderboard(full_cand_text)

    if not user_norm or not cand_norm:
        return 0.0

    # تطابق تام أو احتواء صريح لاسم الشاشة
    label_norm = normalize_arabic_text_leaderboard(label)
    if label_norm and (label_norm in user_norm or user_norm in label_norm):
        return 0.90 if tier >= 1 else 0.55

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
    confidence = min(0.85, 0.40 + (overlap_score * 0.45))
    if is_report_query and any(kw in label_norm for kw in REPORT_INQUIRY_KEYWORDS_NORM):
        confidence = min(0.92, confidence + 0.12)
    elif tier == 0:
        confidence = min(confidence, 0.45)
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
            # Demote secondary details/report/setting/types screens so they never hijack transactional entry
            for i, s in enumerate(scored):
                cand_obj = candidates_map.get(s.id)
                s_lower = f"{s.id} {cand_obj.label if cand_obj else ''} {' '.join(cand_obj.path if cand_obj else [])}".lower()
                if any(kw in s_lower for kw in (
                    "details", "detail", "تقرير", "report", "تفاصيل", "استعلام", "inquiry",
                    "total", "اجمالي", "إجمالي", "setting", "إعدادات", "اعدادات", "setup", "config", "تهيئة",
                    "انواع", "أنواع"
                )):
                    scored[i] = s.model_copy(update={"confidence": 0.0})
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

        # 0.5 High-Speed Catalog Transaction Resolution
        is_report_query = _is_report_or_inquiry_query(user_msg)
        is_ambiguous_inv = _is_ambiguous_invoice_query(user_msg)
        catalog_form = None if (is_report_query or is_ambiguous_inv) else forms_catalog_service.resolve_form_by_text(user_msg)
        matched_catalog_candidate_id = None
        if catalog_form:
            cat_pid = str(catalog_form.get("page_id", "")).strip().lower()
            cat_key = str(catalog_form.get("screen_key", "")).strip().lower()
            cat_name = str(catalog_form.get("name_ar", "")).strip()
            cat_name_norm = normalize_arabic_text_leaderboard(cat_name) if cat_name else ""

            # Pass 1: Strict match by numeric page_id or exact Arabic screen name (avoids shared screen_key collision like "Sales Types" 225 vs 244)
            for c in req.candidates:
                c_id_str = str(c.id).strip().lower()
                c_label_clean = (c.label or "").strip()
                if (cat_pid and c_id_str == cat_pid) or (
                    cat_name and (cat_name == c_label_clean or cat_name_norm == normalize_arabic_text_leaderboard(c_label_clean))
                ):
                    matched_catalog_candidate_id = c.id
                    break

            # Pass 2: Fallback to screen_key only if no page_id/name_ar match was found
            if not matched_catalog_candidate_id and cat_key:
                for c in req.candidates:
                    c_id_str = str(c.id).strip().lower()
                    c_label_clean = (c.label or "").strip()
                    if c_id_str == cat_key and not ("انواع" in c_label_clean or "أنواع" in c_label_clean):
                        matched_catalog_candidate_id = c.id
                        break

            # Guard: do not allow unrequested secondary-module screens (e.g., 6700 E-Invoice Customers or
            # 7059 Farmers Purchases) to hijack primary operational module navigation.
            if matched_catalog_candidate_id and matched_catalog_candidate_id in candidates_map:
                mc = candidates_map[matched_catalog_candidate_id]
                mc_tier, _ = _candidate_priority_tier(user_msg, mc.label or mc.id, mc.path)
                if mc_tier == 0:
                    matched_catalog_candidate_id = None

        # 1. AI router
        intent = "unknown"
        scored_candidates: list[NavScored] = []
        source = "ai"
        if self._gemini_client:
            try:
                # Provide a wide window (up to 60 candidates) prioritized by lexical relevance +
                # main operational module hierarchy + explicit core allowlist (no numeric ID cutoffs).
                candidates_to_score = req.candidates
                if len(candidates_to_score) > 60:
                    scored_pre = sorted(
                        candidates_to_score,
                        key=lambda c: (
                            _compute_lexical_similarity(user_msg, c.label or c.id, c.path),
                            *_candidate_priority_tier(user_msg, c.label or c.id, c.path),
                            1.0 if "الوحدات والبرامج الرئيسية" in (c.path or []) else 0.0,
                        ),
                        reverse=True
                    )
                    candidates_to_score = scored_pre[:60]
                    # Ensure matching catalog candidate is NEVER pruned out of LLM window
                    if matched_catalog_candidate_id and matched_catalog_candidate_id in candidates_map:
                        cat_cand = candidates_map[matched_catalog_candidate_id]
                        if cat_cand not in candidates_to_score:
                            candidates_to_score = [cat_cand] + candidates_to_score[:59]

                candidates_payload = [
                    {"id": c.id, "label": c.label, "path": c.path} for c in candidates_to_score
                ]
                prompt = get_erp_navigation_prompt(
                    user_msg=user_msg,
                    current_path_json=json.dumps(req.current_path, ensure_ascii=False),
                    candidates_json=json.dumps(candidates_payload, ensure_ascii=False, indent=2),
                )
                parsed = await self._generate_json(prompt, timeout=16.0)
                intent, scored_candidates = self._parse_router_output(parsed, candidates_map)
            except Exception as e:
                logger.warning(
                    "AI navigation router failed or timed out, falling back to lexical scoring",
                    error=str(e),
                )
                intent, scored_candidates = "unknown", []

        # 2. Lexical fallback (outage only)
        if not scored_candidates:
            source = "lexical"
            # Infer intent from action signals in query
            is_action_msg = any(w in user_msg.lower() for w in ["سجل", "اضف", "أضف", "انشئ", "أنشئ", "فاتورة", "فاتوره", "قيد", "اذن", "إذن", "دخل"])
            intent = "action" if is_action_msg else "unknown"

            for c in req.candidates:
                score = _compute_lexical_similarity(user_msg, c.label, c.path)
                reason = "مطابقة معجمية للألفاظ والمسار" if score > 0.2 else "مطابقة معجمية منخفضة"
                scored_candidates.append(NavScored(id=c.id, confidence=score, reason=reason))

        # 2.5 Catalog-boost: if transaction form matched with action intent (or navigate when AI had no strong distinct winner),
        # grant top confidence and demote rival generic screens
        top_ai_conf = max((s.confidence for s in scored_candidates), default=0.0)
        should_boost_catalog = bool(
            matched_catalog_candidate_id
            and (
                intent in ("action", "unknown")
                or (intent == "navigate" and (source != "ai" or top_ai_conf < 0.75))
            )
        )
        if should_boost_catalog:
            cat_doc_name = catalog_form.get("name_ar", "المعاملة المطلوبة") if catalog_form else "المعاملة المطلوبة"
            matched_existing = False
            for s in scored_candidates:
                if s.id == matched_catalog_candidate_id:
                    s.confidence = max(s.confidence, 0.98)
                    s.reason = f"مطابقة مباشرة لمعاملة {cat_doc_name} في النظام"
                    matched_existing = True
                else:
                    # Demote rival generic screens so gap threshold cleanly triggers 'go'
                    if s.confidence > 0.60:
                        s.confidence = min(s.confidence, 0.50)
            if not matched_existing and matched_catalog_candidate_id in candidates_map:
                scored_candidates.append(
                    NavScored(
                        id=matched_catalog_candidate_id,
                        confidence=0.98,
                        reason=f"مطابقة مباشرة لمعاملة {cat_doc_name} في النظام"
                    )
                )
            if intent == "unknown":
                intent = "action"

        # 3. Dedupe, penalize detail/report/total screens for action intent, prioritize primary modules, sort, top-3
        has_primary_candidate = any(
            (cand_obj := candidates_map.get(s.id)) is not None
            and _candidate_priority_tier(user_msg, cand_obj.label or cand_obj.id, cand_obj.path)[0] >= 2
            for s in scored_candidates
        )
        unique_scored: dict[str, NavScored] = {}
        for s in scored_candidates:
            cand_obj = candidates_map.get(s.id)
            if intent == "action" and not is_report_query:
                label_lower = f"{cand_obj.label if cand_obj else s.id} {' '.join(cand_obj.path if cand_obj else [])}".lower()
                id_lower = s.id.lower()
                if any(k in id_lower or k in label_lower for k in [
                    "detail", "تفاصيل", "report", "تقرير", "inquiry", "استعلام", "log", "total", "اجمالي", "إجمالي",
                    "setting", "settings", "setup", "config", "configuration", "إعدادات", "اعدادات", "تهيئة", "تهيئه",
                    "انواع", "أنواع"
                ]):
                    # Do not penalize if this was the explicitly matched transaction form
                    if s.id != matched_catalog_candidate_id:
                        s.confidence = 0.0
                        s.reason = "شاشة إعدادات/أنواع/تفاصيل/تقرير غير صالحة لتسجيل أو إنشاء المعاملات"
            if has_primary_candidate and cand_obj is not None:
                c_tier, _ = _candidate_priority_tier(user_msg, cand_obj.label or cand_obj.id, cand_obj.path)
                if c_tier == 0 and s.confidence > 0.50:
                    s = s.model_copy(update={"confidence": 0.50})
            if s.id not in unique_scored or s.confidence > unique_scored[s.id].confidence:
                unique_scored[s.id] = s

        # Generic ambiguous invoice requests ("عايز افتح شاشة الفواتير") must ask between
        # primary operational invoice screens rather than collapsing into clarify or picking 1 blind.
        if is_ambiguous_inv and intent != "question":
            primary_inv_cands = [
                c for c in req.candidates
                if _candidate_priority_tier(user_msg, c.label or c.id, c.path)[0] >= 3
                and "فواتير" in normalize_arabic_text_leaderboard(c.label or "")
            ]
            if len(primary_inv_cands) >= 2:
                prelim = sorted(unique_scored.values(), key=lambda x: x.confidence, reverse=True)[:3]
                if self._decide(prelim) != "ask":
                    intent = "navigate"
                    unique_scored = {}
                    for idx, pc in enumerate(primary_inv_cands[:3]):
                        conf = round(0.78 - (idx * 0.02), 2)
                        unique_scored[pc.id] = NavScored(
                            id=pc.id,
                            confidence=conf,
                            reason="تخيير بين شاشات الفواتير الأساسية في النظام",
                        )

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
        حل وتعبئة الحقول الجديدة أو غير المحسومة التي ظهرت ديناميكياً (Leftover Form Fill)
        باستخدام الذكاء الاصطناعي والمطابقة الدلالية لربط قيم المستخدم بالخيارات المتاحة فعلياً في القوائم المنسدلة.
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
        if not active_fields:
            return LeftoverResponse(fields={}, ask_user=[])

        # مرادفات دلالية ثنائية اللغة للخيارات الشائعة (مثل العملات وطرق الشراء)
        OPTION_SYNONYM_GROUPS: list[set[str]] = [
            {"egp", "مصري", "مصرى", "جنيه", "جنية", "جنيه مصري", "جنية مصري", "جم"},
            {"usd", "دولار", "دولار امريكي", "دولار أمريكي"},
            {"eur", "euro", "يورو"},
            {"aed", "اماراتي", "إماراتي", "درهم", "دينار اماراتي", "درهم اماراتي"},
            {"sar", "سعودي", "ريال", "ريال سعودي"},
        ]

        def _match_option_semantically(val_str: str, options: list[str]) -> str | None:
            norm_v = normalize_arabic_text_leaderboard(val_str).strip().lower()
            if not norm_v:
                return None
            # 1. تطابق حرفي أو معجمي مباشر
            for opt in options:
                norm_opt = normalize_arabic_text_leaderboard(opt).strip().lower()
                if val_str.lower() == opt.lower() or norm_v == norm_opt:
                    return opt
            # 2. تطابق المرادفات الدلالية (مثل مصري <-> EGP)
            for grp in OPTION_SYNONYM_GROUPS:
                if norm_v in grp or any(g in norm_v for g in grp if len(g) >= 3):
                    for opt in options:
                        norm_opt = normalize_arabic_text_leaderboard(opt).strip().lower()
                        if norm_opt in grp:
                            return opt
            # 3. تطابق جزئي مع استبعاد النفي ("غير")
            wants_neg = "غير" in norm_v
            for opt in options:
                norm_opt = normalize_arabic_text_leaderboard(opt).strip().lower()
                if not wants_neg and "غير" in norm_opt:
                    continue
                if norm_v in norm_opt or norm_opt in norm_v:
                    return opt
            return None

        # تجهيز خريطة للبيانات المستخرجة لتسهيل المطابقة (Exact, Lowercase, Normalized Label, Technical Aliases)
        norm_extracted: dict[str, Any] = {}
        for k, v in req.extracted_data.items():
            if v is not None:
                norm_extracted[k] = v
                norm_extracted[k.lower()] = v
                norm_extracted[normalize_arabic_text_leaderboard(str(k))] = v
                # إذا وضع الـ AI قيمة طريقة الشراء في custom_select أو InsertType، نوفرها لـ POSetting / ContractType
                if k.lower() in ("custom_select", "inserttype", "طريقة الشراء", "نوع الشراء"):
                    norm_extracted.setdefault("posetting", v)
                    norm_extracted.setdefault("contracttype", v)

        needs_ai_resolution = False
        for field in active_fields:
            matched_val: Any = None
            field_key_norm = normalize_arabic_text_leaderboard(field.key)
            field_label_norm = normalize_arabic_text_leaderboard(field.label)

            # البحث عن القيمة في البيانات المستخرجة
            if field.key in req.extracted_data:
                matched_val = req.extracted_data[field.key]
            elif field.key.lower() in norm_extracted:
                matched_val = norm_extracted[field.key.lower()]
            elif field.label and field.label in req.extracted_data:
                matched_val = req.extracted_data[field.label]
            elif field_label_norm and field_label_norm in norm_extracted:
                matched_val = norm_extracted[field_label_norm]
            elif field_key_norm and field_key_norm in norm_extracted:
                matched_val = norm_extracted[field_key_norm]

            # فحص خيارات الحقل (options) إن وجدت
            if field.options and len(field.options) > 0:
                if matched_val is not None:
                    str_val = str(matched_val).strip()
                    matched_opt = _match_option_semantically(str_val, field.options)
                    if matched_opt is not None:
                        fields_res[field.key] = matched_opt
                    else:
                        needs_ai_resolution = True
                        ask_user_res.append(field.key)
                else:
                    needs_ai_resolution = True
            else:
                if matched_val is not None:
                    fields_res[field.key] = matched_val
                else:
                    needs_ai_resolution = True

        # الاستعانة بموديل الذكاء الاصطناعي للتفكير الدلالي وربط الحقول والخيارات المتاحة
        if needs_ai_resolution and self._gemini_client and req.user_message.strip():
            try:
                new_fields_payload = [
                    {
                        "key": f.key,
                        "label": f.label,
                        "kind": f.kind,
                        "options": f.options[:30] if f.options else [],
                    }
                    for f in active_fields
                    if f.key not in fields_res
                ]
                if new_fields_payload:
                    prompt = get_erp_leftover_resolution_prompt(
                        user_message=req.user_message,
                        extracted_json=json.dumps(req.extracted_data, ensure_ascii=False),
                        filled_json=json.dumps({**req.filled, **fields_res}, ensure_ascii=False),
                        new_fields_json=json.dumps(new_fields_payload, ensure_ascii=False),
                    )
                    ai_parsed = await self._generate_json(prompt, timeout=10.0)
                    if isinstance(ai_parsed, dict):
                        ai_fields = ai_parsed.get("fields") or {}
                        ai_ask = ai_parsed.get("ask_user") or []
                        fields_by_key = {f.key: f for f in active_fields}
                        if isinstance(ai_fields, dict):
                            for k, v in ai_fields.items():
                                if k in fields_by_key and v is not None and str(v).strip():
                                    f_obj = fields_by_key[k]
                                    if f_obj.options:
                                        # التحقق من أن الخيار الذي اختاره الـ AI موجود في القائمة أو يطابقها
                                        verified_opt = _match_option_semantically(str(v).strip(), f_obj.options)
                                        if verified_opt is not None:
                                            fields_res[k] = verified_opt
                                            if k in ask_user_res:
                                                ask_user_res.remove(k)
                                    else:
                                        fields_res[k] = v
                        if isinstance(ai_ask, list):
                            for ak in ai_ask:
                                if ak in active_keys and ak not in fields_res and ak not in ask_user_res:
                                    ask_user_res.append(ak)
            except Exception as e:
                logger.warning("AI leftover resolution failed, using deterministic matches", error=str(e))

        # ضمان أن جميع المفاتيح في fields و ask_user تنتمي حصراً لمفاتيح new_fields النشطة
        final_fields = {k: v for k, v in fields_res.items() if k in active_keys}
        final_ask_user = [k for k in ask_user_res if k in active_keys and k not in final_fields]

        return LeftoverResponse(fields=final_fields, ask_user=final_ask_user)


erp_service = ErpService()

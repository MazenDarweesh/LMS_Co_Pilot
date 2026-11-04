"""
Semantic Screen Resolver & Lexical Intent Matcher Service.
Provides Arabic morphological tokenization, qualifier boosting, report penalties,
and LLM fallback resolution to accurately resolve natural language goals to ERP screens.
"""

import asyncio
import json
from pathlib import Path
from typing import Any, Optional
import structlog

from google.genai import types
from src.core.config import settings
class _CdpProxy:
    def __getattr__(self, name):
        from src.services.erp_copilot.cdp import cdp_agent_service
        return getattr(cdp_agent_service, name)

cdp_agent_service = _CdpProxy()
from src.services.erp_copilot.forms_catalog_service import forms_catalog_service
from src.services.erp_copilot.vision_grounding_service import vision_grounding_service
from src.services.erp_copilot.agentic_stepper.prompts import get_stepper_screen_resolver_prompt
from src.utils.arabic_speech_utils import normalize_arabic_text_leaderboard

logger = structlog.get_logger()

STOPWORDS = {
    "اذهب", "افتح", "انتقل", "شاشة", "صفحة", "عايز", "محتاج", "ممكن", "اريد", "أريد",
    "الي", "الى", "على", "علي", "من", "في", "عن", "مع", "هذا", "هذه", "ذلك", "اللي", "التي", "الذي", "بها", "له"
}

IRREGULAR_PLURALS = {
    "اوامر": "امر", "فواتير": "فاتورة", "فاتورتها": "فاتورة", "قيود": "قيد", "اصناف": "صنف", "عملاء": "عميل",
    "موردين": "مورد", "مخازن": "مخزن", "شيكات": "شيك", "سندات": "سند", "عقود": "عقد",
    "اصول": "اصل", "رواتب": "راتب", "مرتبات": "مرتب"
}


def clean_token(w: str) -> set[str]:
    """تفكيك الكلمة العربية وإزالة الزوائد والتعريف وربط الجموع الشاذة بالمفرد"""
    res = {w}
    if w.startswith("ال") and len(w) >= 5:
        base = w[2:]
        res.add(base)
    else:
        base = w

    for suffix in ["ات", "ين", "ون", "ية", "يه"]:
        if base.endswith(suffix) and len(base) >= 5:
            res.add(base[:-len(suffix)])

    if base in IRREGULAR_PLURALS:
        res.add(IRREGULAR_PLURALS[base])

    if base.endswith("ه"):
        res.add(base[:-1] + "ت")
    return res


def tokenize(text: str) -> set[str]:
    """تطبيع النص وتفكيكه لمجموعة رموز دلالية صرفية"""
    norm = normalize_arabic_text_leaderboard(text).lower()
    tokens = set()
    for w in norm.split():
        if len(w) >= 3 and w not in STOPWORDS:
            tokens.update(clean_token(w))
    return tokens


class ScreenResolver:
    """
    مسؤول عن المطابقة الدلالية الذكية بين نية المستخدم في هدفه الطبيعي
    والشاشات المصرح بها له أو المسجلة في كتالوج النظام.
    """

    def __init__(self, catalog_path: Optional[Path] = None) -> None:
        self.catalog_path = catalog_path or (Path(__file__).resolve().parent.parent.parent.parent / "data" / "screens_metadata.json")
        self._catalog: Optional[list[dict[str, Any]]] = None
        self._session_screens_cache: dict[str, list[dict[str, Any]]] = {}

    def _load_screens_catalog(self) -> list[dict[str, Any]]:
        """تحميل كتالوج الأوصاف والنوايا الدلالية لشاشات الـ ERP في الذاكرة لمرة واحدة فقط (Singleton Cache)"""
        if self._catalog is not None:
            return self._catalog
        if self.catalog_path.exists():
            try:
                with open(self.catalog_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self._catalog = data.get("screens", [])
            except Exception as e:
                logger.warning("Failed to load screens_metadata.json", error=str(e))
                self._catalog = []
        else:
            self._catalog = []
        return self._catalog

    async def get_cached_user_screens(
        self, ws_url: str, session_id: Optional[str] = None
    ) -> list[dict[str, Any]]:
        """
        جلب وتخزين شاشات المستخدم المصرح بها في الذاكرة (Session-Level Memory Cache).
        يتم استدعاء الفرونت إند عبر CDP مرة واحدة فقط طوال الجلسة، وتكون الاستدعاءات اللاحقة فورية (0ms).
        """
        cache_key = session_id or ws_url
        if cache_key in self._session_screens_cache:
            return self._session_screens_cache[cache_key]

        screens = await cdp_agent_service.get_user_authorized_screens(ws_url)
        if screens:
            self._session_screens_cache[cache_key] = screens
            logger.info("Cached user authorized screens for session", session_id=session_id, count=len(screens))
        return screens or []

    async def resolve_target_screen(
        self, goal: str, authorized_screens: list[dict[str, Any]]
    ) -> Optional[dict[str, Any]]:
        """
        المطابقة الدلالية الذكية بين نية المستخدم في هدفه الطبيعي والشاشات المصرح بها له.
        تدمج بين المطابقة المعجمية السريعة والذكاء الاصطناعي لاختيار الشاشة المحددة بدقة 100%.
        """
        # 0. الفحص الفوري فائق الدقة عبر كتالوج الشاشات المجمع (Forms Catalog O(1) Hash Map)
        catalog_match = forms_catalog_service.resolve_form_by_text(goal)
        if catalog_match and catalog_match.get("page_id"):
            return {
                "page_id": catalog_match.get("page_id"),
                "screen_key": catalog_match.get("screen_key"),
                "name_ar": catalog_match.get("name_ar"),
                "name_en": catalog_match.get("name_en"),
                "module": catalog_match.get("module"),
                "description": catalog_match.get("description", ""),
                "intents": catalog_match.get("intents", []),
            }

        catalog = self._load_screens_catalog()
        norm_goal = normalize_arabic_text_leaderboard(goal).lower()

        # 1. تجميع وتوحيد الشاشات المرشحة من الفرونت إند والكتالوج المرجعي
        pool: list[dict[str, Any]] = []
        if authorized_screens:
            meta_by_key = {s.get("screen_key", "").lower(): s for s in catalog}
            meta_by_id = {s.get("default_page_id"): s for s in catalog if s.get("default_page_id")}
            for auth in authorized_screens:
                k = (auth.get("screen_key") or "").lower()
                pid = auth.get("page_id")
                meta = meta_by_key.get(k) or meta_by_id.get(pid) or {}
                pool.append({
                    "page_id": pid or meta.get("default_page_id"),
                    "screen_key": auth.get("screen_key") or meta.get("screen_key"),
                    "name_ar": auth.get("name_ar") or meta.get("name_ar"),
                    "name_en": auth.get("name_en") or meta.get("name_en"),
                    "module": auth.get("module") or meta.get("module"),
                    "description": meta.get("description", ""),
                    "intents": meta.get("intents", []),
                })
        else:
            for s in catalog:
                pool.append({
                    "page_id": s.get("default_page_id"),
                    "screen_key": s.get("screen_key"),
                    "name_ar": s.get("name_ar"),
                    "name_en": s.get("name_en"),
                    "module": s.get("module"),
                    "description": s.get("description", ""),
                    "intents": s.get("intents", []),
                })

        goal_tokens = tokenize(goal)

        # 3. فحص وتصنيف أولي فائق الدقة بالنوايا والتطابق المباشر
        scored_candidates: list[tuple[float, int, int, int, int, dict[str, Any]]] = []

        for screen in pool:
            score = 0.0
            name_norm = normalize_arabic_text_leaderboard(screen.get("name_ar", "")).lower()
            name_tokens = tokenize(name_norm)

            # أ. تطابق تام أو ترويسة العنوان
            if name_norm and (name_norm in norm_goal or norm_goal in name_norm):
                score = max(score, 1.0)

            # ب. تطابق النوايا الصريحة والمترادفات
            best_intent_overlap = 0
            exact_intent_match = False
            for intent in screen.get("intents", []):
                intent_norm = normalize_arabic_text_leaderboard(intent).lower()
                if intent_norm and intent_norm in norm_goal:
                    score = max(score, 0.98)
                    exact_intent_match = True
                intent_tokens = tokenize(intent)
                overlap = len(goal_tokens & intent_tokens)
                if overlap > best_intent_overlap:
                    best_intent_overlap = overlap

            if best_intent_overlap >= 3:
                score = max(score, 0.95)
            elif best_intent_overlap == 2:
                score = max(score, 0.92)
            elif best_intent_overlap == 1 and not exact_intent_match:
                score = max(score, 0.50)

            # ج. تطابق كلمات عنوان الشاشة
            name_overlap = len(goal_tokens & name_tokens)
            if name_overlap >= 3:
                score = max(score, 0.96)
            elif name_overlap == 2:
                score = max(score, 0.93)
            elif name_overlap == 1:
                score = max(score, 0.65)

            # د. تطابق كلمات الوصف التفصيلي
            desc_tokens = tokenize(screen.get("description", ""))
            desc_hits = len(goal_tokens & desc_tokens)
            if desc_hits >= 3:
                score = max(score, 0.60 + min(0.15, desc_hits * 0.03))

            # هـ. عقوبة شاشات التقارير والاستعلام عند وجود نية تنفيذية (Task A.5: Demotion Penalty)
            is_action_goal = any(v in norm_goal for v in ["سجل", "اضف", "انشئ", "ادخل", "فاتورة", "اعتماد", "طلب", "صرف", "قيد"])
            if is_action_goal:
                disqualified_keywords = ["تقرير", "تفاصيل", "اعدادات", "استعلام", "مصمم", "ملفات"]
                if any(dk in name_norm for dk in disqualified_keywords):
                    score -= 0.35

            # و. تعزيز الكلمات التمييزية الدقيقة (Qualifier Token Boosting)
            if "مقاول" in norm_goal and "مقاول" in name_norm:
                score += 0.30
            if "عميل" in norm_goal and "عميل" in name_norm:
                score += 0.30
            if "سلف" in norm_goal and "سلف" in name_norm:
                score += 0.35
            if "تشغيل" in norm_goal and "تشغيل" in name_norm:
                score += 0.30

            if score > 0.4:
                scored_candidates.append((
                    score,
                    1 if exact_intent_match else 0,
                    name_overlap,
                    best_intent_overlap,
                    desc_hits,
                    screen
                ))

        scored_candidates.sort(key=lambda x: (x[0], x[1], x[2], x[3], x[4]), reverse=True)

        # إذا وجدنا تطابقاً حاسماً (> 0.88)، نختاره فوراً في أقل من 5ms دون استهلاك LLM
        if scored_candidates and scored_candidates[0][0] >= 0.88:
            return scored_candidates[0][5]

        # 4. إذا كان الهدف عاماً جداً أو غامضاً، نستشير GEMINI_MODEL بين أفضل 4 مرشحين
        candidates_to_rank = [c[5] for c in scored_candidates[:4]] if scored_candidates else pool[:6]
        if not candidates_to_rank:
            return None

        if not vision_grounding_service._client:
            vision_grounding_service.initialize()
        client = vision_grounding_service._client
        if not client:
            return candidates_to_rank[0]

        candidates_json = json.dumps(
            [{"page_id": s["page_id"], "name_ar": s["name_ar"], "module": s["module"], "description": s["description"]} for s in candidates_to_rank],
            ensure_ascii=False,
            indent=2,
        )
        prompt = get_stepper_screen_resolver_prompt(goal=goal, candidates_json=candidates_json)
        try:
            resp = await asyncio.wait_for(
                asyncio.to_thread(
                    client.models.generate_content,
                    model=settings.GEMINI_MODEL,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        temperature=0.0,
                    ),
                ),
                timeout=14.0,
            )
            raw = resp.text if hasattr(resp, "text") and resp.text else "{}"
            parsed = json.loads(raw)
            sel_id = parsed.get("selected_page_id")
            for c in candidates_to_rank:
                if c.get("page_id") == sel_id:
                    c["resolution_reason"] = parsed.get("reason", "")
                    return c
        except Exception as e:
            logger.warning("LLM screen resolution failed, falling back to top candidate", error=str(e))

        return candidates_to_rank[0]

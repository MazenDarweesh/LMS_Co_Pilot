import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any, AsyncGenerator, Optional
import structlog

from src.core.config import settings
from src.core.prompts import ERP_PAYMENT_RULES
from google.genai import types
from src.services.cdp_agent_service import cdp_agent_service
from src.services.forms_catalog_service import forms_catalog_service
from src.services.vision_grounding_service import vision_grounding_service
from src.utils.arabic_speech_utils import normalize_arabic_text_leaderboard

logger = structlog.get_logger()

ERP_LOGS_DIR = Path("logs/erp_sessions")
SHARED_LOGS_DIR = Path("e:/Mazen/shared_logs/erp_sessions")


def _append_session_event(session_id: Optional[str], level: str, stage: str, message: str, details: Optional[dict[str, Any]] = None) -> None:
    """تسجيل حدث تفصيلي في ملف الجلسة الأسود الموحد"""
    if not session_id:
        return
    clean_id = re.sub(r"[^a-zA-Z0-9_\-]", "_", session_id)
    filename = f"session_{clean_id}.log"
    iso_now = datetime.now(timezone.utc).isoformat()
    det_str = json.dumps(details or {}, ensure_ascii=False) if details else ""
    line = f"[{iso_now}] [{level.upper()}] [{stage.upper()}] {message} | {det_str}\n"

    unified_filename = "agent_unified_debug.log"
    unified_line = f"[{iso_now}] [{clean_id}] [{level.upper()}] [{stage.upper()}] {message} | {det_str}\n"

    for target_dir in [ERP_LOGS_DIR, SHARED_LOGS_DIR]:
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            # 1. ملف الجلسة المنفصل (للأرشفة المستقلة)
            with open(target_dir / filename, "a", encoding="utf-8") as f:
                f.write(line)
            # 2. ملف السجل الجامع الموحد لوكيل الذكاء الاصطناعي (AI Agent Unified Debug Ledger)
            with open(target_dir / unified_filename, "a", encoding="utf-8") as uf:
                uf.write(unified_line)
        except Exception:
            pass


class AgenticStepperService:
    """
    محرك الأتمتة البصرية المستقل (Autonomous Agentic Stepper).
    ينفذ حلقة التفكير والتنفيذ خطوة بخطوة حتى تحقيق الهدف أو الوصول للحد الأقصى.
    """

    def __init__(self, default_max_steps: int = 15) -> None:
        self.default_max_steps = default_max_steps
        self._catalog: Optional[list[dict[str, Any]]] = None
        self._session_screens_cache: dict[str, list[dict[str, Any]]] = {}

    def _load_screens_catalog(self) -> list[dict[str, Any]]:
        """تحميل كتالوج الأوصاف والنوايا الدلالية لشاشات الـ ERP في الذاكرة لمرة واحدة فقط (Singleton Cache)"""
        if self._catalog is not None:
            return self._catalog
        catalog_path = Path(__file__).resolve().parent.parent / "data" / "screens_metadata.json"
        if catalog_path.exists():
            try:
                with open(catalog_path, "r", encoding="utf-8") as f:
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
        from src.services.forms_catalog_service import forms_catalog_service
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

        # 2. تفكيك وتطبيع الكلمات الدلالية للهدف مع تصريف الجموع والزوائد
        stopwords = {
            "اذهب", "افتح", "انتقل", "شاشة", "صفحة", "عايز", "محتاج", "ممكن", "اريد", "أريد",
            "الي", "الى", "على", "علي", "من", "في", "عن", "مع", "هذا", "هذه", "ذلك", "اللي", "التي", "الذي", "بها", "له"
        }

        def clean_token(w: str) -> set[str]:
            res = {w}
            if w.startswith("ال") and len(w) >= 5:
                base = w[2:]
                res.add(base)
            else:
                base = w

            for suffix in ["ات", "ين", "ون", "ية", "يه"]:
                if base.endswith(suffix) and len(base) >= 5:
                    res.add(base[:-len(suffix)])

            irregulars = {
                "اوامر": "امر", "فواتير": "فاتورة", "فاتورتها": "فاتورة", "قيود": "قيد", "اصناف": "صنف", "عملاء": "عميل",
                "موردين": "مورد", "مخازن": "مخزن", "شيكات": "شيك", "سندات": "سند", "عقود": "عقد",
                "اصول": "اصل", "رواتب": "راتب", "مرتبات": "مرتب"
            }
            if base in irregulars:
                res.add(irregulars[base])

            if base.endswith("ه"):
                res.add(base[:-1] + "ت")
            return res

        def tokenize(text: str) -> set[str]:
            norm = normalize_arabic_text_leaderboard(text).lower()
            tokens = set()
            for w in norm.split():
                if len(w) >= 3 and w not in stopwords:
                    tokens.update(clean_token(w))
            return tokens

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

        prompt = f"""You are an ERP Navigation Resolver for DynamicPro ERP.
Match the user's natural language goal in Arabic to the single best ERP screen from the candidate list below.

USER GOAL:
"{goal}"

CANDIDATE SCREENS:
{json.dumps([{"page_id": s["page_id"], "name_ar": s["name_ar"], "module": s["module"], "description": s["description"]} for s in candidates_to_rank], ensure_ascii=False, indent=2)}

OUTPUT FORMAT (JSON only):
{{
  "selected_page_id": <int>,
  "confidence": <float 0.0 - 1.0>,
  "reason": "سبب موجز لاختيار الشاشة"
}}
"""
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

    async def extract_transaction_payload(
        self,
        goal: str,
        target_screen: Optional[dict[str, Any]] = None,
        target_page_id: Optional[int] = None,
        timeout: float = 15.0,
    ) -> dict[str, Any]:
        """
        استخراج البيانات المنظمة للمعاملة باستخدام الذكاء الاصطناعي (Generic Dynamic AI Extractor)
        بناءً على مخطط النموذج المسجل في كتالوج النماذج أو المولد التلقائي للشاشات غير المسجلة.
        يدعم جميع أنواع المعاملات (فواتير، سلف، قيود، حركات مخازن، مقاولين، إلخ) دون أي كود صلب.
        """
        if not vision_grounding_service._client:
            vision_grounding_service.initialize()
        client = vision_grounding_service._client
        if not client:
            return {"header": {}, "items": []}

        # تحديد المعرف ومخطط الشاشة
        pid = target_page_id or (target_screen.get("page_id") if target_screen else None)
        if not pid:
            direct = forms_catalog_service.resolve_form_by_text(goal)
            if direct:
                pid = direct.get("page_id")

        schema_contract = forms_catalog_service.get_prompt_schema_for_gemini(pid or 289, fallback_meta=target_screen)
        doc_name = schema_contract.get("document_name", "مستند ERP")
        is_excel = schema_contract.get("is_excel", False)
        expected_header = schema_contract.get("expected_header", {})
        expected_grid = schema_contract.get("expected_grid", {})

        extraction_prompt = f"""You are an ERP Document Parser for DynamicPro ERP.
Extract structured transaction data for document '{doc_name}' from the user's natural language goal in Arabic.

USER GOAL:
"{goal}"

DOCUMENT SPECIFICATION:
- Document Type: {doc_name}
- Multi-line Items Grid: {"Yes" if is_excel else "No"}
- Target Page ID: {schema_contract.get("page_id")}
- Target Screen Key: {schema_contract.get("screen_key")}

EXPECTED HEADER FIELDS (Extract values for any matching fields present in the user goal):
{json.dumps(expected_header, ensure_ascii=False, indent=2)}

EXPECTED LINE/GRID FIELDS:
{json.dumps(expected_grid, ensure_ascii=False, indent=2) if is_excel else "None (Single-record form: items must be empty [])"}

RULES:
1. Map values strictly to the matching field keys from EXPECTED HEADER FIELDS and EXPECTED LINE/GRID FIELDS.
2. {ERP_PAYMENT_RULES}
3. Keep values literal as spoken (Arabic names of suppliers, items, warehouses).

OUTPUT FORMAT (JSON only):
{{
  "header": {{
    // Map extracted values strictly to keys from EXPECTED HEADER FIELDS (e.g. VendorID, CustomerID, EmpId, StoreID, Amount, Months, DocDate, Description)
  }},
  "items": [
    // Array of objects matching keys from EXPECTED LINE/GRID FIELDS (e.g. product, productQty, UnitPrice, AccID, Debit, Credit) or empty [] if not applicable
  ],
  "target_page_id": {schema_contract.get("page_id")},
  "document_title": "{doc_name}"
}}
"""
        try:
            resp = await asyncio.wait_for(
                asyncio.to_thread(
                    client.models.generate_content,
                    model=settings.GEMINI_MODEL,
                    contents=extraction_prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        temperature=0.0,
                    ),
                ),
                timeout=timeout,
            )
            raw = resp.text if hasattr(resp, "text") and resp.text else "{}"
            parsed = json.loads(raw)
            if "target_page_id" not in parsed and schema_contract.get("page_id"):
                parsed["target_page_id"] = schema_contract.get("page_id")
            if "document_title" not in parsed:
                parsed["document_title"] = doc_name
            return parsed
        except TimeoutError:
            logger.warning("Timeout extracting structured transaction payload", timeout=timeout)
            return {"header": {}, "items": [], "target_page_id": schema_contract.get("page_id"), "document_title": doc_name}
        except Exception as e:
            logger.warning("Failed to extract structured transaction payload", error=repr(e))
            return {"header": {}, "items": [], "target_page_id": schema_contract.get("page_id"), "document_title": doc_name}

    async def execute_goal_stream(
        self,
        goal: str,
        cdp_port: int = 9222,
        cdp_host: str = "127.0.0.1",
        session_id: Optional[str] = None,
        max_steps: Optional[int] = None,
        title_match: str = "dynamic",
    ) -> AsyncGenerator[dict[str, Any], None]:
        """
        تشغيل حلقة الأتمتة مع بث التقدم للمستخدم لحظة بلحظة (Streaming Generator).
        """
        limit_steps = max_steps or self.default_max_steps
        _append_session_event(session_id, "INFO", "VISION_AGENT", f"Vision Agent goal started: '{goal}'", {
            "goal": goal, "cdp_host": cdp_host, "cdp_port": cdp_port, "max_steps": limit_steps
        })

        yield {
            "step": 0,
            "status": "connecting",
            "message": f"جاري التحقق من الاتصال بالمتصفح النشط على {cdp_host}:{cdp_port} والتشغيل التلقائي إن لزم الأمر...",
        }

        # 1. التحقق من توفر منفذ CDP مع التشغيل الذاتي المعزول إذا كان الاتصال محلياً
        is_cdp_up = await cdp_agent_service.ensure_cdp_available(port=cdp_port, host=cdp_host)
        if not is_cdp_up:
            yield {
                "step": 0,
                "status": "error",
                "message": (
                    f"تعذر العثور على متصفح مفتوح بمنفذ تصحيح الأخطاء ({cdp_host}:{cdp_port}). "
                    "يرجى تشغيل المتصفح بأمر: chrome.exe --remote-debugging-port=9222"
                ),
            }
            return

        # 2. البحث عن التبويب النشط
        tab = await cdp_agent_service.get_active_erp_tab(port=cdp_port, host=cdp_host, title_match=title_match)
        if not tab or not (tab.get("clean_ws_url") or tab.get("webSocketDebuggerUrl")):
            yield {
                "step": 0,
                "status": "error",
                "message": "تم العثور على منفذ المتصفح ولكن لم يتم العثور على تبويب نشط لنظام الـ ERP.",
            }
            return

        ws_url = tab.get("clean_ws_url") or tab.get("webSocketDebuggerUrl", "")
        tab_title = tab.get("title", "ERP Window")
        yield {
            "step": 0,
            "status": "connected",
            "message": f"تم الاتصال بالمتصفح بنجاح! التبويب النشط: '{tab_title}'",
        }

        history: list[dict[str, Any]] = []
        tx_payload: Optional[dict[str, Any]] = None
        authorized_screens: Optional[list[dict[str, Any]]] = None
        import time

        # استخراج الكلمات المفتاحية للهدف لاستخدامها في التحقق الاستباقي (Goal-Reached Pre-check)
        norm_goal = cdp_agent_service.normalize_ar(goal)
        for prefix in ["اذهب الى", "اذهب ل", "افتح", "انتقل الى", "عرض"]:
            norm_prefix = cdp_agent_service.normalize_ar(prefix)
            if norm_goal.startswith(norm_prefix):
                norm_goal = norm_goal[len(norm_prefix):].strip()

        # 3. حلقة التنفيذ التلقائي (Agentic Loop)
        for step_idx in range(1, limit_steps + 1):
            t_step_start = time.perf_counter()
            timings: dict[str, float] = {}

            yield {
                "step": step_idx,
                "status": "observing",
                "message": f"خطوة {step_idx}/{limit_steps}: جاري فحص حالة الصفحة والعناصر التفاعلية...",
            }

            try:
                # أ. استخراج حالة الصفحة ومقاييس الشاشة والعناصر التفاعلية في طلب واحد متزامن (Parallel Gathering)
                t_gather_start = time.perf_counter()
                page_state, viewport_metrics, interactive_elements = await asyncio.gather(
                    cdp_agent_service.get_page_state(ws_url),
                    cdp_agent_service.get_viewport_metrics(ws_url),
                    cdp_agent_service.get_interactive_elements(ws_url),
                    return_exceptions=True
                )
                timings["gather_ms"] = round((time.perf_counter() - t_gather_start) * 1000, 1)

                if isinstance(page_state, Exception) or not isinstance(page_state, dict):
                    page_state = {"url": "", "title": "", "headings": []}
                if isinstance(viewport_metrics, Exception) or not isinstance(viewport_metrics, dict):
                    viewport_metrics = {"width": 1280.0, "height": 720.0, "dpr": 1.0}
                if isinstance(interactive_elements, Exception) or not isinstance(interactive_elements, list):
                    interactive_elements = []

                # ب. التحقق الاستباقي: هل الصفحة الحالية تحقق الهدف بالفعل؟ (Goal-Reached Pre-check)
                curr_url = page_state.get("url", "")
                curr_title = page_state.get("title", "")
                curr_headings = page_state.get("headings", [])
                curr_text = " ".join([curr_url, curr_title] + curr_headings)
                norm_curr = cdp_agent_service.normalize_ar(curr_text)

                # تحديد طبيعة الهدف: هل هو مجرد تنقل لشاشة أم معاملة/إدخال بيانات مركبة؟
                transaction_indicators = (
                    "سجل", "اضف", "أضف", "انشئ", "أنشئ", "ادخل", "أدخل", "تعبئة", "ملء",
                    "كمية", "صنف", "اصناف", "أصناف", "سداد", "سدد", "جديدة", "جديد", "سعر", "مباشرة"
                )
                norm_raw_goal = norm_goal or cdp_agent_service.normalize_ar(goal)
                is_transaction_goal = any(cdp_agent_service.normalize_ar(w) in norm_raw_goal for w in transaction_indicators)

                # ب. مسار أهداف التنقل الدلالي الذكي (Semantic Screen Navigation)
                if not is_transaction_goal:
                    if authorized_screens is None:
                        authorized_screens = await self.get_cached_user_screens(ws_url, session_id=session_id)

                    target_screen = await self.resolve_target_screen(goal, authorized_screens)
                    target_pid = target_screen.get("page_id") if target_screen else None
                    target_title = target_screen.get("name_ar") if target_screen else (norm_goal or goal)

                    active_screen = page_state.get("activeScreen") or {}
                    curr_pid = active_screen.get("pageId")

                    is_already_there = False
                    if target_pid:
                        is_already_there = (
                            (curr_pid == target_pid)
                            or (f"p={target_pid}" in curr_url)
                            or (target_title in curr_title)
                            or any(target_title in h for h in curr_headings)
                        )
                    else:
                        goal_tokens = [cdp_agent_service.normalize_ar(t) for t in goal.split() if len(t) >= 4 and t not in ("اذهب", "افتح", "انتقل", "شاشة", "صفحة")]
                        is_already_there = (norm_goal and len(norm_goal) >= 4 and norm_goal in norm_curr) or (any(token in norm_curr for token in goal_tokens) if goal_tokens else False)

                    if is_already_there:
                        _append_session_event(session_id, "INFO", "VISION_AGENT", f"Step {step_idx}: Target screen '{target_title}' is already open!", {
                            "url": curr_url, "title": curr_title, "headings": curr_headings, "timings_ms": timings
                        })
                        yield {
                            "step": step_idx,
                            "status": "completed",
                            "message": f"✅ أنت بالفعل في شاشة الهدف: '{target_title}' ({curr_headings[0] if curr_headings else curr_url})",
                        }
                        break
                    elif target_pid:
                        _append_session_event(session_id, "INFO", "VISION_AGENT", f"Step {step_idx}: Navigating directly to resolved screen '{target_title}' (PageID {target_pid})...")
                        yield {
                            "step": step_idx,
                            "status": "acting",
                            "message": f"الانتقال المباشر إلى شاشة '{target_title}' (رقم {target_pid})...",
                        }
                        nav_ok = await cdp_agent_service.navigate_to_erp_screen(ws_url, target_pid)
                        await cdp_agent_service.wait_for_settle(ws_url, initial_url=curr_url, max_wait_sec=1.5)
                        history.append({"step": step_idx, "action": "navigate_bridge", "page_id": target_pid, "success": nav_ok})
                        yield {
                            "step": step_idx + 1,
                            "status": "completed",
                            "message": f"✅ تم الانتقال بنجاح إلى شاشة '{target_title}' (رقم {target_pid})!",
                        }
                        break
                else:
                    # ج. مسار المعاملات الهجين الفائق (Hybrid Transaction Execution: Navigation -> Precision Bridge -> Visual Audit)
                    _append_session_event(session_id, "INFO", "VISION_AGENT", f"Step {step_idx}: Transaction goal active on screen '{curr_title}'. Checking screen readiness...")

                    # 1. تحديد الشاشة المستهدفة للمعاملة أولاً لفك الارتباط التام (Decoupled Navigation & Schema Discovery)
                    if authorized_screens is None:
                        authorized_screens = await self.get_cached_user_screens(ws_url, session_id=session_id)
                    target_screen = await self.resolve_target_screen(goal, authorized_screens)
                    tx_page_id = (target_screen.get("page_id") if target_screen else None) or 289
                    target_title = (target_screen.get("name_ar") if target_screen else None) or "المعاملة"

                    # 2. استخراج الـ payload المنظم ديناميكياً بناءً على مواصفات شاشة المعاملة المستهدفة
                    if tx_payload is None:
                        t_extract_start = time.perf_counter()
                        tx_payload = await self.extract_transaction_payload(goal, target_screen=target_screen, target_page_id=tx_page_id)
                        timings["payload_extract_ms"] = round((time.perf_counter() - t_extract_start) * 1000, 1)
                        _append_session_event(session_id, "INFO", "VISION_AGENT", "Extracted transaction payload", tx_payload)

                    active_screen = page_state.get("activeScreen") or {}
                    curr_pid = active_screen.get("pageId")
                    is_on_tx_screen = (
                        (curr_pid == tx_page_id)
                        or (f"{tx_page_id}" in curr_url)
                        or (target_title in curr_title)
                        or any(target_title in h for h in curr_headings)
                    )

                    if not is_on_tx_screen:
                        _append_session_event(session_id, "INFO", "VISION_AGENT", f"Step {step_idx}: Navigating directly to Target Transaction Screen (Page {tx_page_id})...")
                        yield {
                            "step": step_idx,
                            "status": "acting",
                            "message": f"الانتقال المباشر لشاشة المعاملة '{target_title}' (Page {tx_page_id})...",
                        }
                        nav_ok = await cdp_agent_service.navigate_to_erp_screen(ws_url, tx_page_id)
                        await cdp_agent_service.wait_for_settle(ws_url, initial_url=curr_url, max_wait_sec=1.5)
                        history.append({"step": step_idx, "action": "navigate_bridge", "page_id": tx_page_id, "success": nav_ok})
                        continue

                    else:
                        # 3. نحن على شاشة المعاملة -> تنفيذ التعبئة التلقائية الدقيقة عبر الجسر والـ DOM
                        yield {
                            "step": step_idx,
                            "status": "acting",
                            "message": f"جاري تعبئة حقول '{target_title}' بدقة عبر الجسر البرمجي المباشر...",
                        }
                        t_fill_start = time.perf_counter()
                        fill_report = await cdp_agent_service.fill_erp_form_bridge(ws_url, tx_payload)
                        timings["bridge_fill_ms"] = round((time.perf_counter() - t_fill_start) * 1000, 1)
                        _append_session_event(session_id, "INFO", "VISION_AGENT", f"Step {step_idx}: Bridge fill executed", fill_report)
                        await cdp_agent_service.wait_for_settle(ws_url, max_wait_sec=0.8)

                        # 4. التدقيق البصري بالصورة (Vision Screenshot Audit)
                        screenshot_b64 = await cdp_agent_service.capture_screenshot(ws_url, quality=75, mask_chat=True)
                        _append_session_event(session_id, "INFO", "VISION_AGENT", f"Step {step_idx + 1}: Visual verification screenshot captured")

                        # توليد رسالة إنجاز ديناميكية مخصصة للمستند المحدد (Polymorphic Completion Message)
                        form_meta = forms_catalog_service.get_form_by_page_id(tx_page_id)
                        tmpl = (form_meta.get("summary_template_ar") if form_meta else None) or "فاتورة/مستند {document_title}"
                        header_dict = tx_payload.get("header") or {}
                        primary_col = form_meta.get("primary_entity_field") if form_meta else None
                        entity_name = header_dict.get(primary_col) if primary_col else (next(iter(header_dict.values()), "المحدد") if header_dict else "المحدد")
                        lines_count = len(tx_payload.get("items") or tx_payload.get("lines") or [])

                        try:
                            formatted_body = tmpl.format(
                                entity_name=entity_name,
                                lines_count=lines_count,
                                amount=header_dict.get("Amount", ""),
                                months=header_dict.get("Months", ""),
                                date=header_dict.get("DocDate", ""),
                                description=header_dict.get("Description", ""),
                                document_title=target_title,
                                page_id=tx_page_id,
                                movement_type=header_dict.get("MovementType", ""),
                                from_store=header_dict.get("FromStoreID", header_dict.get("StoreName", ""))
                            )
                            done_msg = f"✅ تم تجهيز {formatted_body} بنجاح! راجع البيانات على الشاشة واضغط حفظ."
                        except Exception:
                            done_msg = f"✅ تم تجهيز مستند '{target_title}' وتعبئة البيانات بنجاح! راجع البيانات على الشاشة واضغط حفظ."

                        yield {
                            "step": step_idx + 1,
                            "status": "completed",
                            "message": done_msg,
                        }
                        break

                # ج. وضع القرار الأولي: DOM-First (نصي فائق السرعة وبدون نقل صور)
                t_llm_start = time.perf_counter()
                use_vision_fallback = False
                prediction = await vision_grounding_service.predict_from_elements(
                    goal=goal,
                    elements=interactive_elements,
                    page_state=page_state,
                    history=history,
                    timeout=8.0
                )

                chosen_id = prediction.get("element_id")
                action = prediction.get("action", "wait")
                thought = prediction.get("thought", "")
                is_terminal = prediction.get("is_terminal", False)
                coord = None
                target_text = None

                # إذا اختار النموذج عنصر برقم محدد، نحسب مركزه الفيزيائي الدقيق فوراً
                if action in ("click", "type") and chosen_id is not None and isinstance(chosen_id, int) and 0 <= chosen_id < len(interactive_elements):
                    target_el = interactive_elements[chosen_id]
                    coord = [target_el["x"], target_el["y"]]
                    target_text = target_el.get("text", "")
                    timings["decision_mode"] = "dom_first"
                elif action != "done":
                    # د. خطة الطوارئ البصرية (Vision Fallback): تلتقط صورة مع إخفاء الشات فقط إذا لم يجد العنصر في القائمة
                    use_vision_fallback = True
                    timings["decision_mode"] = "vision_fallback"
                    screenshot_b64 = await cdp_agent_service.capture_screenshot(ws_url, quality=75, mask_chat=True)
                    if screenshot_b64:
                        prediction = await vision_grounding_service.predict_next_action(
                            screenshot_b64=screenshot_b64,
                            goal=goal,
                            history=history,
                            viewport_metrics=viewport_metrics,
                            timeout=12.0
                        )
                        action = prediction.get("action", "wait")
                        thought = prediction.get("thought", "")
                        coord = prediction.get("coordinate")
                        target_text = prediction.get("target_text")
                        is_terminal = prediction.get("is_terminal", False)

                timings["llm_ms"] = round((time.perf_counter() - t_llm_start) * 1000, 1)

                # حارس التكرار (Loop Guard): إذا كرر نفس الإجراء مرتين متتاليتين في نفس الصفحة
                if history and len(history) >= 2:
                    last_h = history[-1]
                    if last_h.get("action") == action and last_h.get("coord") == coord and last_h.get("url") == curr_url:
                        _append_session_event(session_id, "WARN", "VISION_AGENT", "Loop Guard triggered: repeated identical click without navigation. Stopping.")
                        yield {
                            "step": step_idx,
                            "status": "completed",
                            "message": "تم التوقف عند الشاشة الحالية لتفادي تكرار النقر دون تغيير.",
                        }
                        break

                _append_session_event(session_id, "INFO", "VISION_AGENT", f"Step {step_idx}: Action='{action}'", {
                    "step": step_idx,
                    "action": action,
                    "thought": thought,
                    "coordinate": coord,
                    "target_text": target_text,
                    "mode": timings.get("decision_mode", "dom_first"),
                    "timings_ms": timings
                })

                # بث الملاحظة والتفكير للمستخدم
                yield {
                    "step": step_idx,
                    "status": "acting",
                    "thought": thought,
                    "action": action,
                    "coordinate": coord,
                    "message": thought or f"تنفيذ الإجراء: {action}",
                }

                # فحص شرط الانتهاء
                if is_terminal or action == "done":
                    _append_session_event(session_id, "INFO", "VISION_AGENT", f"Step {step_idx}: Goal achieved successfully!")
                    done_msg = "✅ تم إنجاز إعداد المعاملة وتعبئة البيانات بنجاح! راجع الفاتورة على الشاشة واضغط حفظ." if is_transaction_goal else "✅ تم إنجاز المطلوب والوصول للوجهة بنجاح!"
                    yield {
                        "step": step_idx,
                        "status": "completed",
                        "message": done_msg,
                    }
                    break

                # هـ. تنفيذ الإجراء الفيزيائي
                t_exec_start = time.perf_counter()
                if action == "click" and coord and len(coord) == 2:
                    fx, fy, was_snapped = await cdp_agent_service.click_element_or_coordinate(
                        ws_url=ws_url,
                        x=int(coord[0]),
                        y=int(coord[1]),
                        target_text=target_text or thought,
                        interactive_elements=interactive_elements
                    )
                    timings["click_ms"] = round((time.perf_counter() - t_exec_start) * 1000, 1)

                    # و. انتظار ذكي بدلاً من sleep ثابت (Settle Detection)
                    settle_ms = await cdp_agent_service.wait_for_settle(ws_url, initial_url=curr_url, max_wait_sec=0.7)
                    timings["settle_ms"] = round(settle_ms, 1)

                    history.append({
                        "step": step_idx,
                        "action": "click",
                        "coord": [fx, fy],
                        "snapped": was_snapped,
                        "target_text": target_text,
                        "thought": thought,
                        "url": curr_url
                    })

                elif action == "type":
                    # إذا تم تحديد إحداثي الحقل، ننقر عليه أولاً لتفعيله والتركيز عليه
                    if coord and len(coord) == 2:
                        await cdp_agent_service.click_element_or_coordinate(
                            ws_url=ws_url,
                            x=int(coord[0]),
                            y=int(coord[1]),
                            target_text=target_text or thought,
                            interactive_elements=interactive_elements
                        )
                        await asyncio.sleep(0.15)
                    text_to_type = prediction.get("text") or ""
                    if text_to_type:
                        await cdp_agent_service.type_text(ws_url, str(text_to_type))
                    history.append({"step": step_idx, "action": "type", "coord": coord, "text": text_to_type, "thought": thought, "url": curr_url})

                elif action == "press_key" and prediction.get("key"):
                    await cdp_agent_service.press_key(ws_url, str(prediction["key"]))
                    history.append({"step": step_idx, "action": "press_key", "key": prediction["key"], "thought": thought, "url": curr_url})

                elif action == "wait":
                    await asyncio.sleep(0.4)
                    history.append({"step": step_idx, "action": "wait", "thought": thought, "url": curr_url})

                timings["total_step_ms"] = round((time.perf_counter() - t_step_start) * 1000, 1)
                _append_session_event(session_id, "INFO", "VISION_AGENT", f"Step {step_idx} timings", timings)

            except Exception as step_err:
                logger.error("Error during agent step execution", step=step_idx, error=str(step_err))
                _append_session_event(session_id, "ERROR", "VISION_AGENT", f"Step {step_idx} error: {str(step_err)}")
                yield {
                    "step": step_idx,
                    "status": "step_error",
                    "message": f"تنبيه أثناء الخطوة {step_idx}: {str(step_err)} (جاري المتابعة...)",
                }
                await asyncio.sleep(0.3)

        else:
            _append_session_event(session_id, "WARN", "VISION_AGENT", f"Max steps reached ({limit_steps}). Safety stop.")
            yield {
                "step": limit_steps,
                "status": "max_steps_reached",
                "message": f"تم الوصول للحد الأقصى للخطوات ({limit_steps}). توقف العميل لضمان الأمان.",
            }


# Singleton instance
agentic_stepper_service = AgenticStepperService()

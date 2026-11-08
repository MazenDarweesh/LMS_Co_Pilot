"""
Autonomous Stepper Execution Engine.
Orchestrates the multi-step goal execution streaming loop across screen navigation,
transaction form filling, and DOM-first / vision grounding action dispatch.
"""

import asyncio
import time
from typing import Any, AsyncGenerator, Optional
import structlog

from src.services.erp_copilot.agentic_stepper.payload_extractor import PayloadExtractor
from src.services.erp_copilot.agentic_stepper.screen_resolver import ScreenResolver
from src.services.erp_copilot.agentic_stepper.session_telemetry import (
    TelemetryStage,
    append_session_event,
)
class _CdpProxy:
    def __getattr__(self, name):
        from src.services.erp_copilot.cdp import cdp_agent_service
        return getattr(cdp_agent_service, name)

cdp_agent_service = _CdpProxy()
from src.services.erp_copilot.forms_catalog_service import forms_catalog_service
from src.services.erp_copilot.vision_grounding_service import vision_grounding_service

logger = structlog.get_logger()


class StepperEngine:
    """
    محرك التنفيذ التكراري المستقل (Autonomous Execution Engine).
    يدير حلقة التفكير والتنفيذ والتنقل وتعبئة النماذج وبث الأحداث (SSE Stream).
    """

    def __init__(
        self,
        resolver: ScreenResolver,
        extractor: PayloadExtractor,
        default_max_steps: int = 15,
    ) -> None:
        self.resolver = resolver
        self.extractor = extractor
        self.default_max_steps = default_max_steps

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
        append_session_event(
            session_id,
            "INFO",
            TelemetryStage.STEPPER_ENGINE,
            f"Vision Agent goal started: '{goal}'",
            {
                "goal": goal,
                "cdp_host": cdp_host,
                "cdp_port": cdp_port,
                "max_steps": limit_steps,
            },
        )

        yield {
            "step": 0,
            "status": "connecting",
            "message": f"جاري التحقق من الاتصال بالمتصفح النشط على {cdp_host}:{cdp_port} والتشغيل التلقائي إن لزم الأمر...",
        }

        # 1. التحقق من توفر منفذ CDP مع التشغيل الذاتي المعزول إذا كان الاتصال محلياً
        is_cdp_up = await cdp_agent_service.ensure_cdp_available(port=cdp_port, host=cdp_host, session_id=session_id)
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
        tab = await cdp_agent_service.get_active_erp_tab(
            port=cdp_port, host=cdp_host, title_match=title_match, session_id=session_id
        )
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
        consecutive_nav_fails: int = 0

        # استخراج الكلمات المفتاحية للهدف لاستخدامها في التحقق الاستباقي (Goal-Reached Pre-check)
        norm_goal = cdp_agent_service.normalize_ar(goal)
        for prefix in ["اذهب الى", "اذهب ل", "افتح", "انتقل الى", "عرض"]:
            norm_prefix = cdp_agent_service.normalize_ar(prefix)
            if norm_goal.startswith(norm_prefix):
                norm_goal = norm_goal[len(norm_prefix) :].strip()

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
                    return_exceptions=True,
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
                    "كمية", "صنف", "اصناف", "أصناف", "سداد", "سدد", "جديدة", "جديد", "سعر", "مباشرة",
                )
                norm_raw_goal = norm_goal or cdp_agent_service.normalize_ar(goal)
                is_transaction_goal = any(cdp_agent_service.normalize_ar(w) in norm_raw_goal for w in transaction_indicators)

                # مسار أهداف التنقل الدلالي الذكي (Semantic Screen Navigation)
                if not is_transaction_goal:
                    if authorized_screens is None:
                        authorized_screens = await self.resolver.get_cached_user_screens(ws_url, session_id=session_id)

                    target_screen = await self.resolver.resolve_target_screen(goal, authorized_screens)
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
                        goal_tokens = [
                            cdp_agent_service.normalize_ar(t)
                            for t in goal.split()
                            if len(t) >= 4 and t not in ("اذهب", "افتح", "انتقل", "شاشة", "صفحة")
                        ]
                        is_already_there = (
                            (norm_goal and len(norm_goal) >= 4 and norm_goal in norm_curr)
                            or (any(token in norm_curr for token in goal_tokens) if goal_tokens else False)
                        )

                    if is_already_there:
                        append_session_event(
                            session_id,
                            "INFO",
                            TelemetryStage.STEPPER_RESOLVER,
                            f"Step {step_idx}: Target screen '{target_title}' is already open!",
                            {
                                "url": curr_url,
                                "title": curr_title,
                                "headings": curr_headings,
                                "timings_ms": timings,
                            },
                        )
                        yield {
                            "step": step_idx,
                            "status": "completed",
                            "message": f"✅ أنت بالفعل في شاشة الهدف: '{target_title}' ({curr_headings[0] if curr_headings else curr_url})",
                        }
                        break
                    elif target_pid:
                        append_session_event(
                            session_id,
                            "INFO",
                            TelemetryStage.CDP_NAVIGATOR,
                            f"Step {step_idx}: Navigating directly to resolved screen '{target_title}' (PageID {target_pid})...",
                        )
                        yield {
                            "step": step_idx,
                            "status": "acting",
                            "message": f"الانتقال المباشر إلى شاشة '{target_title}' (رقم {target_pid})...",
                        }
                        nav_ok = await cdp_agent_service.navigate_to_erp_screen(ws_url, target_pid, session_id=session_id)
                        settle_ms = await cdp_agent_service.wait_for_settle(ws_url, initial_url=curr_url, max_wait_sec=2.5)

                        # التحقق الاستباقي من الوصول الفعلي للشاشة المستهدفة (Per-Step Verification)
                        verify_state = await cdp_agent_service.get_page_state(ws_url)
                        verify_url = verify_state.get("url", "")
                        verify_screen = verify_state.get("activeScreen") or {}
                        arrived = (
                            verify_screen.get("pageId") == target_pid
                            or f"{target_pid}" in verify_url
                            or target_title in verify_state.get("title", "")
                            or any(target_title in h for h in verify_state.get("headings", []))
                        )
                        history.append({"step": step_idx, "action": "navigate_bridge", "page_id": target_pid, "success": nav_ok and arrived})
                        append_session_event(
                            session_id,
                            "INFO" if arrived else "WARN",
                            TelemetryStage.STEPPER_VERIFY,
                            f"Step {step_idx}: Navigation verify {'PASSED' if arrived else 'FAILED'} (settle={settle_ms:.0f}ms)",
                            {"target_pid": target_pid, "verify_url": verify_url, "arrived": arrived},
                        )
                        if not arrived:
                            yield {"step": step_idx, "status": "acting", "message": f"⚠️ لم يُتحقق من الوصول لشاشة '{target_title}' — إعادة المحاولة..."}
                            continue
                        yield {
                            "step": step_idx + 1,
                            "status": "completed",
                            "message": f"✅ تم الانتقال والتحقق من الوصول بنجاح إلى شاشة '{target_title}' (رقم {target_pid})!",
                        }
                        break
                else:
                    # مسار المعاملات الهجين الفائق (Hybrid Transaction Execution: Navigation -> Precision Bridge -> Visual Audit)
                    append_session_event(
                        session_id,
                        "INFO",
                        TelemetryStage.STEPPER_ENGINE,
                        f"Step {step_idx}: Transaction goal active on screen '{curr_title}'. Checking screen readiness...",
                    )

                    # 1. تحديد الشاشة المستهدفة للمعاملة أولاً لفك الارتباط التام (Decoupled Navigation & Schema Discovery)
                    if authorized_screens is None:
                        authorized_screens = await self.resolver.get_cached_user_screens(ws_url, session_id=session_id)
                    target_screen = await self.resolver.resolve_target_screen(goal, authorized_screens)
                    tx_page_id = (target_screen.get("page_id") if target_screen else None) or 289
                    target_title = (target_screen.get("name_ar") if target_screen else None) or "المعاملة"

                    # 2. استخراج الـ payload المنظم ديناميكياً بناءً على مواصفات شاشة المعاملة المستهدفة
                    if tx_payload is None:
                        t_extract_start = time.perf_counter()
                        tx_payload = await self.extractor.extract_transaction_payload(
                            goal, target_screen=target_screen, target_page_id=tx_page_id
                        )
                        if isinstance(tx_payload, dict) and any(
                            kw in goal.lower() for kw in ("نقد", "كاش", "سدد", "مدفوع", "محصل", "cash")
                        ):
                            hdr = tx_payload.setdefault("header", {})
                            if isinstance(hdr, dict) and not any(
                                any(pk in k.lower() for pk in ("popaid", "cashpaid", "madfou", "مدفوع", "محصل"))
                                for k in hdr
                            ):
                                hdr["POPaidCurrancy"] = "$TOTAL"
                        timings["payload_extract_ms"] = round((time.perf_counter() - t_extract_start) * 1000, 1)
                        append_session_event(
                            session_id,
                            "INFO",
                            TelemetryStage.STEPPER_EXTRACTOR,
                            "Extracted transaction payload",
                            tx_payload,
                        )

                    active_screen = page_state.get("activeScreen") or {}
                    curr_pid = active_screen.get("pageId")
                    is_on_tx_screen = (
                        (curr_pid == tx_page_id)
                        or (f"{tx_page_id}" in curr_url)
                        or (target_title in curr_title)
                        or any(target_title in h for h in curr_headings)
                    )

                    if not is_on_tx_screen:
                        append_session_event(
                            session_id,
                            "INFO",
                            TelemetryStage.CDP_NAVIGATOR,
                            f"Step {step_idx}: Navigating directly to Target Transaction Screen (Page {tx_page_id})...",
                        )
                        yield {
                            "step": step_idx,
                            "status": "acting",
                            "message": f"الانتقال المباشر لشاشة المعاملة '{target_title}' (Page {tx_page_id})...",
                        }

                        # استراتيجية متكيفة: إذا فشلت الملاحة البرمجية بالجسر، الانتقال فوراً للنقر المباشر على DOM
                        if consecutive_nav_fails >= 1:
                            append_session_event(
                                session_id,
                                "INFO",
                                TelemetryStage.CDP_NAVIGATOR,
                                f"Step {step_idx}: Using fallback DOM-click navigation to page {tx_page_id}",
                            )
                            nav_ok = await cdp_agent_service.navigate_to_erp_screen_dom_click(
                                ws_url, tx_page_id, session_id=session_id
                            )
                        else:
                            nav_ok = await cdp_agent_service.navigate_to_erp_screen(
                                ws_url, tx_page_id, session_id=session_id
                            )

                        settle_ms = await cdp_agent_service.wait_for_settle(ws_url, initial_url=curr_url, max_wait_sec=2.5)

                        # التحقق الشامل من الوصول الفعلي (Per-Step Verification)
                        verify_state = await cdp_agent_service.get_page_state(ws_url)
                        verify_url = verify_state.get("url", "")
                        verify_title = verify_state.get("title", "")
                        verify_headings = verify_state.get("headings", [])
                        verify_screen = verify_state.get("activeScreen") or {}
                        verify_pid = verify_screen.get("pageId")

                        tx_arrived = (
                            verify_pid == tx_page_id
                            or (bool(verify_url) and f"{tx_page_id}" in verify_url)
                            or target_title in verify_title
                            or any(target_title in h for h in verify_headings)
                        )

                        history.append({
                            "step": step_idx,
                            "action": "navigate_bridge" if consecutive_nav_fails == 0 else "navigate_dom_click",
                            "page_id": tx_page_id,
                            "success": nav_ok and tx_arrived,
                        })
                        append_session_event(
                            session_id,
                            "INFO" if tx_arrived else "WARN",
                            TelemetryStage.STEPPER_VERIFY,
                            f"Step {step_idx}: TX Screen Navigation verify {'PASSED' if tx_arrived else 'FAILED'} (settle={settle_ms:.0f}ms)",
                            {
                                "target_pid": tx_page_id,
                                "verify_pid": verify_pid,
                                "verify_url": verify_url,
                                "tx_arrived": tx_arrived,
                                "consecutive_nav_fails": consecutive_nav_fails,
                            },
                        )
                        if not tx_arrived:
                            consecutive_nav_fails += 1
                            if consecutive_nav_fails >= 4:
                                append_session_event(
                                    session_id,
                                    "ERROR",
                                    TelemetryStage.CDP_NAVIGATOR,
                                    f"Navigation aborted after {consecutive_nav_fails} consecutive failed attempts to reach page {tx_page_id}",
                                )
                                yield {
                                    "step": step_idx,
                                    "status": "failed",
                                    "message": f"تعذر الوصول لشاشة '{target_title}' (Page {tx_page_id}) بعد {consecutive_nav_fails} محاولات متتالية.",
                                }
                                break
                            yield {
                                "step": step_idx,
                                "status": "acting",
                                "message": f"⚠️ لم يُتحقق من الوصول لشاشة '{target_title}' — تجربة استراتيجية بديلة...",
                            }
                        else:
                            consecutive_nav_fails = 0
                        continue

                    else:
                        consecutive_nav_fails = 0
                        # 3. نحن على شاشة المعاملة -> تنفيذ التعبئة التلقائية الدقيقة عبر الجسر والـ DOM
                        yield {
                            "step": step_idx,
                            "status": "acting",
                            "message": f"جاري تعبئة حقول '{target_title}' بدقة عبر الجسر البرمجي المباشر...",
                        }
                        # 2.5 ضمان فتح فورم الإنشاء (إضافة جديد) قبل التعبئة - مرحلة ensure_form_open
                        open_res = await cdp_agent_service.ensure_erp_form_open(ws_url, session_id=session_id)
                        append_session_event(
                            session_id,
                            "INFO" if open_res.get("opened") else "WARN",
                            TelemetryStage.CDP_FORM_BRIDGE,
                            f"Step {step_idx}: ensure_form_open",
                            open_res,
                        )
                        if not open_res.get("opened"):
                            history.append({"step": step_idx, "action": "open_form", "success": False})
                            yield {"step": step_idx, "status": "acting", "message": f"تعذر فتح فورم '{target_title}' - إعادة المحاولة..."}
                            continue
                        await cdp_agent_service.wait_for_settle(ws_url, max_wait_sec=1.0)
                        pre_snapshot = await cdp_agent_service.snapshot_form_state(ws_url)
                        append_session_event(
                            session_id,
                            "INFO",
                            TelemetryStage.CDP_FORM_BRIDGE,
                            f"Step {step_idx}: form fields discovered before fill",
                            pre_snapshot,
                        )

                        t_fill_start = time.perf_counter()
                        fill_report = await cdp_agent_service.fill_erp_form_bridge(
                            ws_url, tx_payload, session_id=session_id
                        )
                        timings["bridge_fill_ms"] = round((time.perf_counter() - t_fill_start) * 1000, 1)
                        append_session_event(
                            session_id,
                            "INFO",
                            TelemetryStage.CDP_FORM_BRIDGE,
                            f"Step {step_idx}: Bridge fill executed",
                            fill_report,
                        )
                        post_snapshot = await cdp_agent_service.snapshot_form_state(ws_url)
                        append_session_event(
                            session_id,
                            "INFO",
                            TelemetryStage.CDP_FORM_BRIDGE,
                            f"Step {step_idx}: form model after fill",
                            {"model": post_snapshot.get("model"), "totals": post_snapshot.get("totals")},
                        )
                        if not fill_report.get("success"):
                            history.append({"step": step_idx, "action": "fill_form", "success": False})
                            yield {"step": step_idx, "status": "acting", "message": "لم تُملأ أي حقول - إعادة المحاولة..."}
                            continue
                        await cdp_agent_service.wait_for_settle(ws_url, max_wait_sec=0.8)

                        # 4. التدقيق البصري بالصورة (Vision Screenshot Audit)
                        await cdp_agent_service.capture_screenshot(ws_url, quality=75, mask_chat=True)
                        append_session_event(
                            session_id,
                            "INFO",
                            TelemetryStage.CDP_VISUAL,
                            f"Step {step_idx + 1}: Visual verification screenshot captured",
                        )

                        # توليد رسالة إنجاز ديناميكية مخصصة للمستند المحدد (Polymorphic Completion Message)
                        form_meta = forms_catalog_service.get_form_by_page_id(tx_page_id)
                        tmpl = (form_meta.get("summary_template_ar") if form_meta else None) or "فاتورة/مستند {document_title}"
                        header_dict = tx_payload.get("header") or {}
                        primary_col = form_meta.get("primary_entity_field") if form_meta else None
                        entity_name = (
                            header_dict.get(primary_col)
                            if primary_col
                            else (next(iter(header_dict.values()), "المحدد") if header_dict else "المحدد")
                        )
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
                                from_store=header_dict.get("FromStoreID", header_dict.get("StoreName", "")),
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

                # وضع القرار الأولي: DOM-First (نصي فائق السرعة وبدون نقل صور)
                t_llm_start = time.perf_counter()
                prediction = await vision_grounding_service.predict_from_elements(
                    goal=goal,
                    elements=interactive_elements,
                    page_state=page_state,
                    history=history,
                    timeout=8.0,
                )

                chosen_id = prediction.get("element_id")
                action = prediction.get("action", "wait")
                thought = prediction.get("thought", "")
                is_terminal = prediction.get("is_terminal", False)
                coord = None
                target_text = None

                # إذا اختار النموذج عنصر برقم محدد، نحسب مركزه الفيزيائي الدقيق فوراً
                if (
                    action in ("click", "type")
                    and chosen_id is not None
                    and isinstance(chosen_id, int)
                    and 0 <= chosen_id < len(interactive_elements)
                ):
                    target_el = interactive_elements[chosen_id]
                    coord = [target_el["x"], target_el["y"]]
                    target_text = target_el.get("text", "")
                    timings["decision_mode"] = "dom_first"
                elif action != "done":
                    # خطة الطوارئ البصرية (Vision Fallback): تلتقط صورة مع إخفاء الشات فقط إذا لم يجد العنصر في القائمة
                    timings["decision_mode"] = "vision_fallback"
                    screenshot_b64 = await cdp_agent_service.capture_screenshot(ws_url, quality=75, mask_chat=True)
                    if screenshot_b64:
                        prediction = await vision_grounding_service.predict_next_action(
                            screenshot_b64=screenshot_b64,
                            goal=goal,
                            history=history,
                            viewport_metrics=viewport_metrics,
                            timeout=12.0,
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
                        append_session_event(
                            session_id,
                            "WARN",
                            TelemetryStage.STEPPER_ENGINE,
                            "Loop Guard triggered: repeated identical click without navigation. Stopping.",
                        )
                        yield {
                            "step": step_idx,
                            "status": "completed",
                            "message": "تم التوقف عند الشاشة الحالية لتفادي تكرار النقر دون تغيير.",
                        }
                        break

                append_session_event(
                    session_id,
                    "INFO",
                    TelemetryStage.STEPPER_ENGINE,
                    f"Step {step_idx}: Action='{action}'",
                    {
                        "step": step_idx,
                        "action": action,
                        "thought": thought,
                        "coordinate": coord,
                        "target_text": target_text,
                        "mode": timings.get("decision_mode", "dom_first"),
                        "timings_ms": timings,
                    },
                )

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
                    append_session_event(
                        session_id,
                        "INFO",
                        TelemetryStage.STEPPER_ENGINE,
                        f"Step {step_idx}: Goal achieved successfully!",
                    )
                    done_msg = (
                        "✅ تم إنجاز إعداد المعاملة وتعبئة البيانات بنجاح! راجع الفاتورة على الشاشة واضغط حفظ."
                        if is_transaction_goal
                        else "✅ تم إنجاز المطلوب والوصول للوجهة بنجاح!"
                    )
                    yield {
                        "step": step_idx,
                        "status": "completed",
                        "message": done_msg,
                    }
                    break

                # تنفيذ الإجراء الفيزيائي
                t_exec_start = time.perf_counter()
                if action == "click" and coord and len(coord) == 2:
                    fx, fy, was_snapped = await cdp_agent_service.click_element_or_coordinate(
                        ws_url=ws_url,
                        x=int(coord[0]),
                        y=int(coord[1]),
                        target_text=target_text or thought,
                        interactive_elements=interactive_elements,
                    )
                    timings["click_ms"] = round((time.perf_counter() - t_exec_start) * 1000, 1)

                    # انتظار ذكي بدلاً من sleep ثابت (Settle Detection)
                    settle_ms = await cdp_agent_service.wait_for_settle(ws_url, initial_url=curr_url, max_wait_sec=0.7)
                    timings["settle_ms"] = round(settle_ms, 1)

                    history.append({
                        "step": step_idx,
                        "action": "click",
                        "coord": [fx, fy],
                        "snapped": was_snapped,
                        "target_text": target_text,
                        "thought": thought,
                        "url": curr_url,
                    })

                elif action == "type":
                    # إذا تم تحديد إحداثي الحقل، ننقر عليه أولاً لتفعيله والتركيز عليه
                    if coord and len(coord) == 2:
                        await cdp_agent_service.click_element_or_coordinate(
                            ws_url=ws_url,
                            x=int(coord[0]),
                            y=int(coord[1]),
                            target_text=target_text or thought,
                            interactive_elements=interactive_elements,
                        )
                        await asyncio.sleep(0.15)
                    text_to_type = prediction.get("text") or ""
                    if text_to_type:
                        await cdp_agent_service.type_text(ws_url, str(text_to_type))
                    history.append({
                        "step": step_idx,
                        "action": "type",
                        "coord": coord,
                        "text": text_to_type,
                        "thought": thought,
                        "url": curr_url,
                    })

                elif action == "press_key" and prediction.get("key"):
                    await cdp_agent_service.press_key(ws_url, str(prediction["key"]))
                    history.append({
                        "step": step_idx,
                        "action": "press_key",
                        "key": prediction["key"],
                        "thought": thought,
                        "url": curr_url,
                    })

                elif action == "wait":
                    await asyncio.sleep(0.4)
                    history.append({"step": step_idx, "action": "wait", "thought": thought, "url": curr_url})

                timings["total_step_ms"] = round((time.perf_counter() - t_step_start) * 1000, 1)
                append_session_event(session_id, "INFO", TelemetryStage.STEPPER_ENGINE, f"Step {step_idx} timings", timings)

            except Exception as step_err:
                logger.error("Error during agent step execution", step=step_idx, error=str(step_err))
                append_session_event(session_id, "ERROR", TelemetryStage.STEPPER_ENGINE, f"Step {step_idx} error: {str(step_err)}")
                yield {
                    "step": step_idx,
                    "status": "step_error",
                    "message": f"تنبيه أثناء الخطوة {step_idx}: {str(step_err)} (جاري المتابعة...)",
                }
                await asyncio.sleep(0.3)

        else:
            append_session_event(session_id, "WARN", TelemetryStage.STEPPER_ENGINE, f"Max steps reached ({limit_steps}). Safety stop.")
            yield {
                "step": limit_steps,
                "status": "max_steps_reached",
                "message": f"تم الوصول للحد الأقصى للخطوات ({limit_steps}). توقف العميل لضمان الأمان.",
            }

import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any, AsyncGenerator, Optional
import structlog

from src.services.cdp_agent_service import cdp_agent_service
from src.services.vision_grounding_service import vision_grounding_service

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

    for target_dir in [ERP_LOGS_DIR, SHARED_LOGS_DIR]:
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            with open(target_dir / filename, "a", encoding="utf-8") as f:
                f.write(line)
        except Exception:
            pass


class AgenticStepperService:
    """
    محرك الأتمتة البصرية المستقل (Autonomous Agentic Stepper).
    ينفذ حلقة التفكير والتنفيذ خطوة بخطوة حتى تحقيق الهدف أو الوصول للحد الأقصى.
    """

    def __init__(self, default_max_steps: int = 15) -> None:
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
        _append_session_event(session_id, "INFO", "VISION_AGENT", f"Vision Agent goal started: '{goal}'", {
            "goal": goal, "cdp_host": cdp_host, "cdp_port": cdp_port, "max_steps": limit_steps
        })

        yield {
            "step": 0,
            "status": "connecting",
            "message": f"جاري التحقق من الاتصال بالمتصفح النشط على {cdp_host}:{cdp_port} عبر بروتوكول CDP...",
        }

        # 1. التحقق من توفر منفذ CDP
        is_cdp_up = await cdp_agent_service.is_cdp_available(port=cdp_port, host=cdp_host)
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
        if not tab or not tab.get("webSocketDebuggerUrl"):
            yield {
                "step": 0,
                "status": "error",
                "message": "تم العثور على منفذ المتصفح ولكن لم يتم العثور على تبويب نشط لنظام الـ ERP.",
            }
            return

        ws_url = tab["webSocketDebuggerUrl"]
        tab_title = tab.get("title", "ERP Window")
        yield {
            "step": 0,
            "status": "connected",
            "message": f"تم الاتصال بالمتصفح بنجاح! التبويب النشط: '{tab_title}'",
        }

        history: list[dict[str, Any]] = []
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

                # فحص تطابق الهدف كاملاً أو الكلمات الأساسية البارزة (مثل المشتريات أو الموردين)
                goal_tokens = [cdp_agent_service.normalize_ar(t) for t in goal.split() if len(t) >= 4 and t not in ("اذهب", "افتح", "انتقل", "شاشة", "صفحة")]
                has_full_match = norm_goal and len(norm_goal) >= 4 and norm_goal in norm_curr
                has_token_match = any(token in norm_curr for token in goal_tokens) if goal_tokens else False

                if has_full_match or has_token_match:
                    _append_session_event(session_id, "INFO", "VISION_AGENT", f"Step {step_idx}: Target screen already reached (Title/Heading match)!", {
                        "url": curr_url, "title": curr_title, "headings": curr_headings, "timings_ms": timings
                    })
                    yield {
                        "step": step_idx,
                        "status": "completed",
                        "message": f"✅ تم الوصول إلى شاشة الهدف بنجاح! ({curr_headings[0] if curr_headings else curr_url})",
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
                if action == "click" and chosen_id is not None and isinstance(chosen_id, int) and 0 <= chosen_id < len(interactive_elements):
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
                    yield {
                        "step": step_idx,
                        "status": "completed",
                        "message": "✅ تم إنجاز المطلوب والوصول للوجهة بنجاح!",
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

                elif action == "type" and prediction.get("text"):
                    await cdp_agent_service.type_text(ws_url, str(prediction["text"]))
                    history.append({"step": step_idx, "action": "type", "text": prediction["text"], "thought": thought, "url": curr_url})

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

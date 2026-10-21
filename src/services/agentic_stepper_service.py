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

        # 3. حلقة التنفيذ التلقائي (Agentic Loop)
        for step_idx in range(1, limit_steps + 1):
            yield {
                "step": step_idx,
                "status": "observing",
                "message": f"خطوة {step_idx}/{limit_steps}: جاري التقاط لقطة الشاشة وتحليل العناصر بصرياً...",
            }

            try:
                # التقاط لقطة الشاشة
                screenshot_b64 = await cdp_agent_service.capture_screenshot(ws_url, quality=75)
                if not screenshot_b64:
                    _append_session_event(session_id, "ERROR", "VISION_AGENT", f"Step {step_idx}: Failed to capture screenshot")
                    yield {
                        "step": step_idx,
                        "status": "error",
                        "message": "فشل التقاط صورة من المتصفح.",
                    }
                    break

                # استخراج أبعاد الشاشة ومعدل الـ DPI
                viewport_metrics = await cdp_agent_service.get_viewport_metrics(ws_url)

                # استنتاج الخطوة عبر Gemini Multimodal
                prediction = await vision_grounding_service.predict_next_action(
                    screenshot_b64=screenshot_b64,
                    goal=goal,
                    history=history,
                    viewport_metrics=viewport_metrics,
                    timeout=14.0,
                )

                action = prediction.get("action", "wait")
                thought = prediction.get("thought", "")
                coord = prediction.get("coordinate")
                text = prediction.get("text")
                key = prediction.get("key")
                is_terminal = prediction.get("is_terminal", False)

                _append_session_event(session_id, "INFO", "VISION_AGENT", f"Step {step_idx}: Action='{action}'", {
                    "step": step_idx,
                    "action": action,
                    "thought": thought,
                    "coordinate": coord,
                    "text": text,
                    "key": key,
                    "is_terminal": is_terminal
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
                        "message": "✅ تم إنجاز إعداد المعاملة وتعبئة البيانات بنجاح! راجع الفاتورة على الشاشة واضغط حفظ.",
                    }
                    break

                # تنفيذ الإجراء الفيزيائي عبر CDP
                if action == "click" and coord and len(coord) == 2:
                    await cdp_agent_service.click_at(ws_url, int(coord[0]), int(coord[1]))
                    history.append({"step": step_idx, "action": "click", "coord": coord, "thought": thought})

                elif action == "type" and text:
                    await cdp_agent_service.type_text(ws_url, str(text))
                    history.append({"step": step_idx, "action": "type", "text": text, "thought": thought})

                elif action == "press_key" and key:
                    await cdp_agent_service.press_key(ws_url, str(key))
                    history.append({"step": step_idx, "action": "press_key", "key": key, "thought": thought})

                elif action == "wait":
                    await asyncio.sleep(0.8)
                    history.append({"step": step_idx, "action": "wait", "thought": thought})

                # إتاحة مهلة قصيرة للـ Angular للرندرة والتفاعل
                await asyncio.sleep(0.4)

            except Exception as step_err:
                logger.error("Error during agent step execution", step=step_idx, error=str(step_err))
                _append_session_event(session_id, "ERROR", "VISION_AGENT", f"Step {step_idx} error: {str(step_err)}")
                yield {
                    "step": step_idx,
                    "status": "step_error",
                    "message": f"تنبيه أثناء الخطوة {step_idx}: {str(step_err)} (جاري المتابعة...)",
                }
                await asyncio.sleep(0.5)

        else:
            _append_session_event(session_id, "WARN", "VISION_AGENT", f"Max steps reached ({limit_steps}). Safety stop.")
            yield {
                "step": limit_steps,
                "status": "max_steps_reached",
                "message": f"تم الوصول للحد الأقصى للخطوات ({limit_steps}). توقف العميل لضمان الأمان.",
            }


# Singleton instance
agentic_stepper_service = AgenticStepperService()

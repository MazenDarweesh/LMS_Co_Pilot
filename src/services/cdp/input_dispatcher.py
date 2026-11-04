"""
CDP Low-Level Protocol & Hardware Input Dispatcher.
Executes raw CDP commands, JavaScript evaluation, dual-action mouse clicks, text typing,
and virtual keyboard key events.
"""

import asyncio
from typing import Any, Callable, Coroutine
import structlog

from src.services.cdp.connection_manager import CdpConnectionManager
from src.services.cdp.script_loader import get_script

logger = structlog.get_logger()


class CdpInputDispatcher:
    """
    مسؤول عن إرسال أوامر بروتوكول CDP منخفضة المستوى ومحاكاة أحداث الفأرة ولوحة المفاتيح
    على مستوى العتاد (Hardware Events) بالتوازي مع تنشيط أحداث DOM المباشرة.
    """

    def __init__(self, connection_manager: CdpConnectionManager) -> None:
        self.conn = connection_manager
        self._ripple_callback: Callable[[str, int, int], Coroutine[Any, Any, None]] | None = None

    def set_ripple_callback(
        self, callback: Callable[[str, int, int], Coroutine[Any, Any, None]]
    ) -> None:
        """تسجيل دالة استدعاء لعرض التموج البصري مكان النقر (Visual Ripple)"""
        self._ripple_callback = callback

    async def execute_cdp_command(
        self, ws_url: str, method: str, params: dict[str, Any] | None = None, timeout: float = 6.0
    ) -> dict[str, Any]:
        """
        إرسال أمر CDP واستلام الرد عبر pydoll ConnectionHandler مع إبقاء الاتصال (Keep-Alive Re-use)
        وإدارة تزامن الأوامر (Command Futures) لمنع تداخل الرسائل عبر الـ WebSocket.
        """
        command = {"method": method, "params": params or {}}
        cmd_timeout = int(max(round(timeout), 1))
        handler = await self.conn.get_pydoll_handler(ws_url)

        try:
            res = await handler.execute_command(command, timeout=cmd_timeout)
            return res.get("result", {})
        except Exception as e:
            logger.debug(
                "pydoll execute_cdp_command failed or disconnected, retrying once with fresh handler",
                method=method,
                error=str(e),
            )
            await self.conn.drop_handler(ws_url)
            fresh_handler = await self.conn.get_pydoll_handler(ws_url)
            res = await fresh_handler.execute_command(command, timeout=cmd_timeout)
            return res.get("result", {})

    async def evaluate_script(self, ws_url: str, script: str, timeout: float = 15.0) -> Any:
        """تنفيذ كود JavaScript في سياق التبويب واسترجاع القيمة"""
        res = await self.execute_cdp_command(
            ws_url,
            "Runtime.evaluate",
            {"expression": script, "returnByValue": True, "awaitPromise": True},
            timeout=timeout,
        )
        return res.get("result", {}).get("value")

    async def click_at(self, ws_url: str, x: int, y: int) -> None:
        """
        تنفيذ نقرة ماوس موثوقة ومزدوجة:
        1. إظهار المؤشر البصري للنقرة (Visual Ripple).
        2. تشغيل تسلسل الأحداث المباشر على العنصر في الـ DOM عبر elementFromPoint.
        3. إرسال أحداث ماوس عتادية كاملة عبر بروتوكول CDP (Input.dispatchMouseEvent).
        """
        # 0. إظهار المؤشر البصري للنقرة إن وجد
        if self._ripple_callback:
            try:
                await self._ripple_callback(ws_url, x, y)
            except Exception as e:
                logger.debug("Ripple callback execution skipped", error=str(e))
        await asyncio.sleep(0.04)

        # 1. نقر مباشر للعنصر عبر JavaScript DOM Dispatch المحمل من ملف dom_click.js
        dom_click_script = get_script("dom_click.js", X=x, Y=y)
        try:
            hit_tag = await self.evaluate_script(ws_url, dom_click_script)
            logger.info("DOM element click dispatched via elementFromPoint", tag=hit_tag, x=x, y=y)
        except Exception as e:
            logger.warn("DOM elementFromPoint click failed", error=str(e))

        # 2. إرسال أحداث العتاد عبر CDP (Hardware-Level Mouse Event)
        try:
            await self.execute_cdp_command(
                ws_url,
                "Input.dispatchMouseEvent",
                {"type": "mouseMoved", "x": x, "y": y},
            )
            await asyncio.sleep(0.05)

            await self.execute_cdp_command(
                ws_url,
                "Input.dispatchMouseEvent",
                {"type": "mousePressed", "x": x, "y": y, "button": "left", "clickCount": 1},
            )
            await asyncio.sleep(0.08)

            await self.execute_cdp_command(
                ws_url,
                "Input.dispatchMouseEvent",
                {"type": "mouseReleased", "x": x, "y": y, "button": "left", "clickCount": 1},
            )
            logger.info("CDP Mouse Click dispatched", x=x, y=y)
        except Exception as e:
            logger.error("CDP hardware mouse click failed", error=str(e))

    async def type_text(self, ws_url: str, text: str, delay_ms: float = 30) -> None:
        """
        كتابة نص باستخدام إدخال الكيبورد المباشر (Input.insertText).
        تدعم النصوص العربية بالكامل والمسافات.
        """
        await self.execute_cdp_command(
            ws_url,
            "Input.insertText",
            {"text": text},
        )
        logger.info("CDP Text typed successfully", length=len(text), snippet=text[:15])

    async def press_key(self, ws_url: str, key_name: str) -> None:
        """
        إرسال ضغطة زر خاصة (Enter, Tab, Escape, Backspace).
        """
        key_codes = {
            "Enter": {"key": "Enter", "code": "Enter", "windowsVirtualKeyCode": 13},
            "Tab": {"key": "Tab", "code": "Tab", "windowsVirtualKeyCode": 9},
            "Escape": {"key": "Escape", "code": "Escape", "windowsVirtualKeyCode": 27},
            "Backspace": {"key": "Backspace", "code": "Backspace", "windowsVirtualKeyCode": 8},
        }
        spec = key_codes.get(key_name, {"key": key_name, "code": key_name})

        await self.execute_cdp_command(
            ws_url,
            "Input.dispatchKeyEvent",
            {"type": "rawKeyDown", **spec},
        )
        await asyncio.sleep(0.05)
        await self.execute_cdp_command(
            ws_url,
            "Input.dispatchKeyEvent",
            {"type": "keyUp", **spec},
        )
        logger.info("CDP Key pressed", key=key_name)

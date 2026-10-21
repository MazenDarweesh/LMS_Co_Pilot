"""
CDP (Chrome DevTools Protocol) Agent Service.
Enables autonomous AI Vision Agent execution directly inside the user's active browser window.
Eliminates session/login friction by connecting to Chrome/Edge via CDP WebSocket (default port 9222).
"""

import asyncio
import json
from typing import Any, Optional
import httpx
import structlog
import websockets

logger = structlog.get_logger()


class CdpAgentService:
    """
    خدمة التحكم المباشر في المتصفح عبر بروتوكول Chrome DevTools Protocol (CDP).
    تتيح التقاط الشاشة (Screenshot) وإرسال نقرات الماوس وأزرار الكيبورد الموثوقة (Hardware-Level Events).
    """

    def __init__(self, default_port: int = 9222) -> None:
        self.default_port = default_port
        self._msg_id = 0

    def _next_id(self) -> int:
        self._msg_id += 1
        return self._msg_id

    def _resolve_urls(self, host: str, port: int) -> tuple[str, str]:
        """
        يحول host و port إلى رابط HTTP ورابط WebSocket متوافقين:
        1. IP مباشر: '192.168.1.61' -> 'http://192.168.1.61:9222', 'ws://192.168.1.61:9222'
        2. رابط نفق: 'https://xxx.devtunnels.ms' -> 'https://xxx.devtunnels.ms', 'wss://xxx.devtunnels.ms'
        """
        clean_h = host.strip().rstrip("/")
        if clean_h.startswith("https://"):
            base_http = clean_h
            base_ws = "wss://" + clean_h[len("https://"):]
        elif clean_h.startswith("http://"):
            base_http = clean_h
            base_ws = "ws://" + clean_h[len("http://"):]
        else:
            base_http = f"http://{clean_h}:{port}"
            base_ws = f"ws://{clean_h}:{port}"
        return base_http, base_ws

    async def is_cdp_available(self, port: Optional[int] = None, host: str = "127.0.0.1") -> bool:
        """فحص ما إذا كان المتصفح يعمل مع منفذ تصحيح الأخطاء المفتوح"""
        p = port or self.default_port
        h = host or "127.0.0.1"
        base_http, _ = self._resolve_urls(h, p)
        try:
            async with httpx.AsyncClient(timeout=1.5, verify=False) as client:
                res = await client.get(f"{base_http}/json/version")
                return res.status_code == 200
        except Exception:
            return False

    async def get_active_erp_tab(self, port: Optional[int] = None, host: str = "127.0.0.1", title_match: str = "") -> Optional[dict[str, Any]]:
        """
        البحث عن التبويب النشط لنظام DynamicPro ERP واستخراج عنوان الـ WebSocket للتصحيح.
        """
        p = port or self.default_port
        h = host or "127.0.0.1"
        base_http, base_ws = self._resolve_urls(h, p)
        try:
            async with httpx.AsyncClient(timeout=2.0, verify=False) as client:
                res = await client.get(f"{base_http}/json")
                if res.status_code != 200:
                    return None
                tabs: list[dict[str, Any]] = res.json()
                pages = [t for t in tabs if t.get("type") == "page"]
                if not pages:
                    return None

                target_tab = pages[0]
                # أولوية 1: التبويب الذي يحتوي على كلمة dynamic أو العنوان المطلوب
                if title_match:
                    for t in pages:
                        title = t.get("title", "").lower()
                        url = t.get("url", "").lower()
                        if title_match.lower() in title or title_match.lower() in url:
                            target_tab = t
                            break

                # ضبط عنوان الـ WebSocket للتوافق مع IP أو نفق الجهاز المستهدف
                ws_url = target_tab.get("webSocketDebuggerUrl", "")
                if ws_url:
                    import re
                    match = re.search(r"/(devtools/.*)$", ws_url)
                    if match:
                        target_tab["webSocketDebuggerUrl"] = f"{base_ws}/{match.group(1)}"

                return target_tab
        except Exception as e:
            logger.warning("Failed to discover Chrome tabs over CDP", error=str(e), host=h, port=p)
            return None

    async def execute_cdp_command(
        self, ws_url: str, method: str, params: Optional[dict[str, Any]] = None, timeout: float = 6.0
    ) -> dict[str, Any]:
        """إرسال أمر CDP مفرد واستلام الرد عبر WebSocket"""
        cmd_id = self._next_id()
        payload = {"id": cmd_id, "method": method, "params": params or {}}

        async with websockets.connect(ws_url, ping_interval=None, max_size=20 * 1024 * 1024) as ws:
            await ws.send(json.dumps(payload))
            while True:
                resp_raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
                data = json.loads(resp_raw)
                if data.get("id") == cmd_id:
                    if "error" in data:
                        raise RuntimeError(f"CDP command {method} failed: {data['error']}")
                    return data.get("result", {})

    async def capture_screenshot(self, ws_url: str, quality: int = 80) -> str:
        """
        التقاط لقطة شاشة للتبويب وإرجاعها كـ Base64 JPEG مضغوطة وسريعة للرؤية البصرية.
        """
        res = await self.execute_cdp_command(
            ws_url,
            "Page.captureScreenshot",
            {"format": "jpeg", "quality": quality, "captureBeyondViewport": False},
            timeout=8.0,
        )
        return res.get("data", "")

    async def get_viewport_metrics(self, ws_url: str) -> dict[str, float]:
        """
        استخراج أبعاد الـ Viewport ومعدل تكبير الشاشة (DevicePixelRatio / Windows DPI) بدقة.
        """
        try:
            metrics = await self.evaluate_script(
                ws_url,
                """({
                    innerWidth: window.innerWidth,
                    innerHeight: window.innerHeight,
                    devicePixelRatio: window.devicePixelRatio || 1,
                    scrollX: window.scrollX || 0,
                    scrollY: window.scrollY || 0
                })"""
            )
            if isinstance(metrics, dict):
                return {
                    "width": float(metrics.get("innerWidth", 1280)),
                    "height": float(metrics.get("innerHeight", 720)),
                    "dpr": float(metrics.get("devicePixelRatio", 1.0)),
                }
        except Exception as e:
            logger.warn("Failed to get viewport metrics over CDP", error=str(e))
        return {"width": 1280.0, "height": 720.0, "dpr": 1.0}

    async def show_click_ripple(self, ws_url: str, x: int, y: int) -> None:
        """
        حقن مؤشر بصري ينبض (Visual Ripple Effect) مكان النقر على شاشة المستخدم لحظياً.
        """
        ripple_script = f"""
        (function() {{
            const existing = document.getElementById('cdp-click-indicator');
            if (existing) existing.remove();
            const dot = document.createElement('div');
            dot.id = 'cdp-click-indicator';
            dot.style.position = 'fixed';
            dot.style.left = '{x}px';
            dot.style.top = '{y}px';
            dot.style.width = '24px';
            dot.style.height = '24px';
            dot.style.marginLeft = '-12px';
            dot.style.marginTop = '-12px';
            dot.style.borderRadius = '50%';
            dot.style.border = '2px solid #ef4444';
            dot.style.backgroundColor = 'rgba(239, 68, 68, 0.35)';
            dot.style.boxShadow = '0 0 12px #ef4444';
            dot.style.pointerEvents = 'none';
            dot.style.zIndex = '2147483647';
            dot.style.transition = 'transform 0.4s ease-out, opacity 0.4s ease-out';
            dot.style.transform = 'scale(0.5)';
            dot.style.opacity = '1';
            document.body.appendChild(dot);
            requestAnimationFrame(() => {{
                dot.style.transform = 'scale(1.6)';
                dot.style.opacity = '0';
            }});
            setTimeout(() => dot.remove(), 500);
        }})();
        """
        try:
            await self.evaluate_script(ws_url, ripple_script)
        except Exception:
            pass

    async def click_at(self, ws_url: str, x: int, y: int) -> None:
        """
        تنفيذ نقرة ماوس موثوقة على مستوى العتاد (Hardware-Level Mouse Click) عند الإحداثيات [x, y].
        تتجاوز حماية الـ PointerEvents وتفعّل الأحداث الداخلية للمتصفح.
        """
        # 0. إظهار المؤشر البصري للنقرة
        await self.show_click_ripple(ws_url, x, y)
        await asyncio.sleep(0.04)

        # 1. تحريك الماوس
        await self.execute_cdp_command(
            ws_url,
            "Input.dispatchMouseEvent",
            {"type": "mouseMoved", "x": x, "y": y},
        )
        await asyncio.sleep(0.05)

        # 2. ضغط زر الماوس الأيسر
        await self.execute_cdp_command(
            ws_url,
            "Input.dispatchMouseEvent",
            {"type": "mousePressed", "x": x, "y": y, "button": "left", "clickCount": 1},
        )
        await asyncio.sleep(0.08)

        # 3. إفلات زر الماوس
        await self.execute_cdp_command(
            ws_url,
            "Input.dispatchMouseEvent",
            {"type": "mouseReleased", "x": x, "y": y, "button": "left", "clickCount": 1},
        )
        logger.info("CDP Mouse Click dispatched", x=x, y=y)

    async def type_text(self, ws_url: str, text: str, delay_ms: float = 30) -> None:
        """
        كتابة نص باستخدام إدخال الكيبورد المباشر (Input.insertText أو dispatchKeyEvent).
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

    async def evaluate_script(self, ws_url: str, script: str) -> Any:
        """تنفيذ كود JavaScript في سياق التبويب واسترجاع القيمة"""
        res = await self.execute_cdp_command(
            ws_url,
            "Runtime.evaluate",
            {"expression": script, "returnByValue": True, "awaitPromise": True},
        )
        return res.get("result", {}).get("value")


# Singleton instance
cdp_agent_service = CdpAgentService()

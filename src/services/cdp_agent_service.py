"""
CDP (Chrome DevTools Protocol) Agent Service.
Enables autonomous AI Vision Agent execution directly inside the user's active browser window.
Eliminates session/login friction by connecting to Chrome/Edge via CDP WebSocket (default port 9222).
"""

import asyncio
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from typing import Any
import httpx
from pydoll.connection.connection_handler import ConnectionHandler
import structlog
import websockets

from src.core.config import settings

logger = structlog.get_logger()


class CdpAgentService:
    """
    خدمة التحكم المباشر في المتصفح عبر بروتوكول Chrome DevTools Protocol (CDP).
    تتيح التقاط الشاشة (Screenshot) وإرسال نقرات الماوس وأزرار الكيبورد الموثوقة (Hardware-Level Events).
    مقسّمة إلى 5 مناطق هندسية (Regions) لتسهيل الصيانة وتتبع الأخطاء بدقة.
    """

    def __init__(self, default_port: int = 9222) -> None:
        self.default_port = default_port
        self._chrome_proc: subprocess.Popen | None = None
        self._http_client: httpx.AsyncClient | None = None
        self._pydoll_handlers: dict[str, ConnectionHandler] = {}
        self._handler_lock = asyncio.Lock()

    async def _get_http_client(self) -> httpx.AsyncClient:
        """إرجاع عميل HTTP مشترك مدار لتجنب إنشاء اتصالات متكررة واستنزاف المقابس"""
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(timeout=4.0, verify=False)
        return self._http_client

    async def _get_pydoll_handler(self, ws_url: str) -> ConnectionHandler:
        """الحصول على كائن ConnectionHandler مدار من مكتبة pydoll مع إبقاء الاتصال وإعادة الاتصال الذاتي"""
        async with self._handler_lock:
            handler = self._pydoll_handlers.get(ws_url)
            is_alive = False
            if handler is not None and handler._ws_connection is not None:
                is_alive = not handler._ws_connection.closed

            if not is_alive:
                if handler is not None:
                    try:
                        await handler.close()
                    except Exception as e:
                        logger.debug("Closing dead pydoll handler failed", ws_url=ws_url, error=str(e))
                handler = ConnectionHandler(ws_address=ws_url)
                self._pydoll_handlers[ws_url] = handler
            return handler

    async def aclose(self) -> None:
        """إغلاق الموارد المشتركة بأمان عند إيقاف الخدمة أو انتهاء الجلسة"""
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()
            self._http_client = None
        async with self._handler_lock:
            for ws_url, handler in list(self._pydoll_handlers.items()):
                try:
                    await handler.close()
                except Exception as e:
                    logger.debug("Closing pydoll connection handler failed", ws_url=ws_url, error=str(e))
            self._pydoll_handlers.clear()

    # ==============================================================================
    # region 1: Lifecycle & Connection Management (إدارة دورة الحياة واكتشاف التبويبات)
    # ==============================================================================

    def _resolve_urls(self, host: str, port: int) -> tuple[str, str]:
        """
        يحول host و port إلى رابط HTTP ورابط WebSocket متوافقين:
        1. IP مباشر: '192.168.1.61' -> 'http://192.168.1.61:9222', 'ws://192.168.1.61:9222'
        2. رابط نفق: 'https://xxx.devtunnels.ms' -> 'https://xxx.devtunnels.ms', 'wss://xxx.devtunnels.ms'
        """
        clean_h = host.strip().rstrip("/")

        # التعامل الآلي الصارم مع أنفاق مايكروسوفت السحابية DevTunnels
        if ".devtunnels.ms" in clean_h:
            if not clean_h.startswith("http"):
                clean_h = "https://" + clean_h
            clean_h = re.sub(r":\d+$", "", clean_h)
            base_http = clean_h
            base_ws = "wss://" + clean_h[len("https://"):]
            return base_http, base_ws

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

    async def is_cdp_available(self, port: int | None = None, host: str = "127.0.0.1") -> bool:
        """فحص ما إذا كان المتصفح يعمل مع منفذ تصحيح الأخطاء المفتوح مع إعادة المحاولة للأنفاق السحابية"""
        p = port or self.default_port
        h = host or "127.0.0.1"
        base_http, _ = self._resolve_urls(h, p)
        client = await self._get_http_client()

        for attempt in range(2):
            try:
                res = await client.get(f"{base_http}/json/version")
                if res.status_code == 200:
                    return True
            except Exception as e:
                logger.debug("is_cdp_available attempt failed", attempt=attempt, host=h, port=p, error=str(e))
                if attempt == 0:
                    await asyncio.sleep(0.35)
        return False

    async def ensure_cdp_available(self, port: int | None = None, host: str = "127.0.0.1") -> bool:
        """
        فحص توفر منفذ تصحيح الأخطاء، وإذا كان الاتصال محلياً والمنفذ مغلقاً،
        يقوم تلقائياً بتشغيل متصفح Chrome بمنفذ تصحيح الأخطاء 9222 وبروفايل معزول لضمان عمل الوكيل فوراً بدون أوامر يدوية.
        مع تقييد عنوان الربط أمنياً على 127.0.0.1 افتراضياً لمنع تعرض منفذ التصحيح لشبكة LAN.
        """
        p = port or self.default_port
        h = host or "127.0.0.1"
        if await self.is_cdp_available(p, h):
            return True

        clean_h = h.lower().replace("http://", "").replace("https://", "").split(":")[0]
        if clean_h in ("127.0.0.1", "localhost"):
            logger.info("Local Chrome CDP offline; auto-spawning Chrome with remote debugging...", port=p)
            try:
                chrome_candidates = [
                    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                    shutil.which("chrome"),
                    shutil.which("google-chrome"),
                    shutil.which("chromium"),
                ]
                chrome_path = next((c for c in chrome_candidates if c and os.path.exists(c)), None)
                if chrome_path:
                    user_data = r"C:\chrome-dev-profile"
                    os.makedirs(user_data, exist_ok=True)

                    # أمان: الاستماع لـ 127.0.0.1 افتراضياً لمنع كشف الـ DevTools لشبكة LAN
                    bind_address = getattr(settings, "CDP_REMOTE_DEBUGGING_ADDRESS", "127.0.0.1")
                    cmd = [
                        chrome_path,
                        f"--remote-debugging-port={p}",
                        f"--remote-debugging-address={bind_address}",
                        f"--user-data-dir={user_data}",
                        "--no-first-run",
                        "--no-default-browser-check",
                        "http://localhost:4200/core",
                    ]
                    creationflags = 0
                    if sys.platform == "win32":
                        DETACHED_PROCESS = 0x00000008
                        CREATE_NEW_PROCESS_GROUP = 0x00000200
                        creationflags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP

                    self._chrome_proc = subprocess.Popen(
                        cmd,
                        creationflags=creationflags,
                        close_fds=True,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    logger.info("Chrome auto-spawned successfully with PID", pid=self._chrome_proc.pid)

                    # فحص الإتاحة لمدة تصل إلى 5 ثوانٍ
                    for _ in range(10):
                        await asyncio.sleep(0.5)
                        if await self.is_cdp_available(p, h):
                            logger.info("Auto-spawned Chrome CDP is now online and reachable ✅", port=p)
                            return True
            except Exception as e:
                logger.error("Failed to auto-launch Chrome with CDP", error=str(e))

        return False

    async def get_active_erp_tab(self, port: int | None = None, host: str = "127.0.0.1", title_match: str = "") -> dict[str, Any] | None:
        """
        البحث عن التبويب النشط لنظام DynamicPro ERP واستخراج عنوان الـ WebSocket للتصحيح مع إعادة المحاولة.
        """
        p = port or self.default_port
        h = host or "127.0.0.1"
        base_http, base_ws = self._resolve_urls(h, p)
        client = await self._get_http_client()

        for attempt in range(2):
            try:
                res = await client.get(f"{base_http}/json")
                if res.status_code != 200:
                    continue
                tabs: list[dict[str, Any]] = res.json()
                pages = [t for t in tabs if t.get("type") == "page"]
                if not pages:
                    # إنشاء تبويب ERP جديد فوراً إذا لم يكن هناك تبويبات صفحات مفتوحة
                    try:
                        new_tab_res = await client.put(f"{base_http}/json/new?http://localhost:4200/core")
                        if new_tab_res.status_code == 200:
                            await asyncio.sleep(1.0)
                            pages = [new_tab_res.json()]
                    except Exception as tab_err:
                        logger.debug("Auto-creating ERP tab failed", error=str(tab_err))

                if not pages:
                    continue

                target_tab = pages[0]
                # أولوية 1: التبويب الذي يحتوي على كلمة dynamic أو core أو العنوان المطلوب
                for t in pages:
                    title = t.get("title", "").lower()
                    url = t.get("url", "").lower()
                    if (
                        (title_match and title_match.lower() in title)
                        or (title_match and title_match.lower() in url)
                        or "dynamic" in title
                        or "dynamic" in url
                        or "4200" in url
                        or "core" in url
                    ):
                        target_tab = t
                        break

                # ضبط عنوان الـ WebSocket للتوافق مع IP أو نفق الجهاز المستهدف
                tab_id = target_tab.get("id")
                if tab_id:
                    clean_ws_base = base_ws.rstrip("/")
                    ws_url = f"{clean_ws_base}/devtools/page/{tab_id}"
                    target_tab["webSocketDebuggerUrl"] = ws_url
                    target_tab["clean_ws_url"] = ws_url
                return target_tab
            except Exception as e:
                logger.debug("get_active_erp_tab attempt failed", attempt=attempt, error=str(e))
                if attempt == 0:
                    await asyncio.sleep(0.35)
        return None

    # endregion

    # ==============================================================================
    # region 2: Low-Level CDP Protocol & Input Dispatch (بروتوكول CDP ونبضات الهاردوير)
    # ==============================================================================

    async def execute_cdp_command(
        self, ws_url: str, method: str, params: dict[str, Any] | None = None, timeout: float = 6.0
    ) -> dict[str, Any]:
        """
        إرسال أمر CDP واستلام الرد عبر pydoll ConnectionHandler مع إبقاء الاتصال (Keep-Alive Re-use)
        وإدارة تزامن الأوامر (Command Futures) لمنع تداخل الرسائل عبر الـ WebSocket.
        """
        command = {"method": method, "params": params or {}}
        cmd_timeout = int(max(round(timeout), 1))
        handler = await self._get_pydoll_handler(ws_url)

        try:
            res = await handler.execute_command(command, timeout=cmd_timeout)
            return res.get("result", {})
        except Exception as e:
            logger.debug(
                "pydoll execute_cdp_command failed or disconnected, retrying once with fresh handler",
                method=method,
                error=str(e),
            )
            async with self._handler_lock:
                old_h = self._pydoll_handlers.pop(ws_url, None)
                if old_h:
                    try:
                        await old_h.close()
                    except Exception:
                        pass

            fresh_handler = await self._get_pydoll_handler(ws_url)
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
        2. تشغيل تسلسل الأحداث المباشر على العنصر في الـ DOM عبر elementFromPoint (لتجاوز أي مشاكل في معالجة أحداث العتاد في Angular/Chromium).
        3. إرسال أحداث ماوس عتادية كاملة عبر بروتوكول CDP (Input.dispatchMouseEvent).
        """
        # 0. إظهار المؤشر البصري للنقرة
        await self.show_click_ripple(ws_url, x, y)
        await asyncio.sleep(0.04)

        # 1. نقر مباشر للعنصر عبر JavaScript DOM Dispatch (يحاكي ضغطة المستخدم تماماً داخل Angular)
        dom_click_script = f"""
        (function() {{
            const el = document.elementFromPoint({x}, {y});
            if (el) {{
                try {{ el.focus(); }} catch(_) {{}}
                const opts = {{ bubbles: true, cancelable: true, view: window, clientX: {x}, clientY: {y} }};
                el.dispatchEvent(new MouseEvent('mousedown', opts));
                el.dispatchEvent(new MouseEvent('mouseup', opts));
                el.dispatchEvent(new MouseEvent('click', opts));
                if (typeof el.click === 'function') {{
                    el.click();
                }}
                // إذا كان العنصر ابن لرابط أو زر أو tile، اضغط الأب أيضاً
                const parentInteractive = el.closest('button, a, [role="button"], .dp-mods__card, .dp-rise, .dp-btn, .dp-pgs__tile, .dp-pgs__mod, .dp-hdr__tab, [routerlink]');
                if (parentInteractive && parentInteractive !== el) {{
                    parentInteractive.dispatchEvent(new MouseEvent('click', opts));
                    if (typeof parentInteractive.click === 'function') {{
                        parentInteractive.click();
                    }}
                }}
                return el.tagName;
            }}
            return null;
        }})();
        """
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

    # endregion

    # ==============================================================================
    # region 3: Visual Grounding & DOM Inspection (الرصد البصري وفحص الاستقرار)
    # ==============================================================================

    @staticmethod
    def normalize_ar(s: str) -> str:
        """
        تطبيع النصوص العربية لإزالة فروق الهمزات والتاء المربوطة والألف المقصورة وعلامات التشكيل.
        مع الاحتفاظ بحروف الكلمة الأصلية وتجنب حذف حرف الواو عشوائياً.
        """
        if not s:
            return ""
        s = re.sub(r"[\u064B-\u065F\u0670]", "", s)
        s = re.sub(r"[أإآٱ]", "ا", s)
        s = re.sub(r"ة", "ه", s)
        s = re.sub(r"[ىي]", "ي", s)
        s = re.sub(r"[\s_\-]+", " ", s).strip().lower()
        return s

    async def capture_screenshot(self, ws_url: str, quality: int = 80, mask_chat: bool = True) -> str:
        """
        التقاط لقطة شاشة للتبويب وإرجاعها كـ Base64 JPEG مضغوطة وسريعة للرؤية البصرية.
        مع إخفاء نافذة المساعد الذكي لحظياً أثناء اللقطة حتى لا تشتت الرؤية وتسبب محاولات إغلاق وهمية.
        """
        if mask_chat:
            try:
                await self.evaluate_script(
                    ws_url,
                    """document.querySelectorAll('lms-copilot-chat, .ai-chat-window, .copilot-window').forEach(el => el.style.visibility = 'hidden');"""
                )
            except Exception as e:
                logger.debug("Failed to mask chat window before screenshot", error=str(e))

        try:
            res = await self.execute_cdp_command(
                ws_url,
                "Page.captureScreenshot",
                {"format": "jpeg", "quality": quality, "captureBeyondViewport": False},
                timeout=8.0,
            )
            return res.get("data", "")
        finally:
            if mask_chat:
                try:
                    await self.evaluate_script(
                        ws_url,
                        """document.querySelectorAll('lms-copilot-chat, .ai-chat-window, .copilot-window').forEach(el => el.style.visibility = '');"""
                    )
                except Exception as e:
                    logger.debug("Failed to unmask chat window after screenshot", error=str(e))

    async def get_page_state(self, ws_url: str) -> dict[str, Any]:
        """استخراج حالة الصفحة الحالية: الرابط، العنوان، النصوص البارزة، والشاشة النشطة حالياً عبر الجسر"""
        script = """
        (function() {
            const headings = [];
            document.querySelectorAll('h1, h2, h3, .dp-list__ttl, .dp-hdr__tab--active, .active').forEach(el => {
                const txt = (el.innerText || el.textContent || '').trim();
                if (txt && txt.length < 100) headings.push(txt);
            });
            let activeScreen = null;
            try {
                if (window.DynamicERP && typeof window.DynamicERP.getActiveScreen === 'function') {
                    activeScreen = window.DynamicERP.getActiveScreen();
                }
            } catch(e) {}

            if (!activeScreen) {
                try {
                    const baseEl = document.querySelector('app-base');
                    if (window.ng && window.ng.getComponent && baseEl) {
                        const comp = window.ng.getComponent(baseEl);
                        const ps = comp ? comp.pageService : null;
                        const curr = ps && ps.getCurrentOpenPage ? ps.getCurrentOpenPage() : null;
                        if (curr) {
                            activeScreen = {
                                pageId: curr.PageID || curr.page_id,
                                pageName: (curr.PageName || curr.screen_key || '').trim(),
                                title: curr.ArName || curr.name_ar || (curr.PageName || '').trim()
                            };
                        }
                    }
                } catch(e) {}
            }

            return {
                url: window.location.href,
                title: document.title,
                headings: headings.slice(0, 5),
                activeScreen: activeScreen
            };
        })()
        """
        try:
            res = await self.evaluate_script(ws_url, script)
            if isinstance(res, dict):
                return res
        except Exception as e:
            logger.warn("Failed to get page state", error=str(e))
        return {"url": "", "title": "", "headings": [], "activeScreen": None}

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
        except Exception as e:
            logger.debug("show_click_ripple skipped", error=str(e))

    async def get_interactive_elements(self, ws_url: str) -> list[dict[str, Any]]:
        """
        استخراج قائمة العناصر التفاعلية الظاهرة حالياً في الصفحة (أزرار، قوائم، روابط، حقول إدخال)
        مع إحداثياتها الدقيقة في الـ DOM (getBoundingClientRect).
        """
        scanner_script = """
        (function() {
            const results = [];
            const selectors = [
                'button', 'a', '[role="button"]', '[role="tab"]', '[role="menuitem"]',
                '.dp-hdr__tab', '.dp-pgs__tile', '.dp-pgs__mod', '.dp-mods__card', '.dp-rise',
                '.dp-btn', '.nav-link', '.menu-item',
                'input:not([type="hidden"])', 'select', 'ng-select', '.ng-select',
                'body > ng-dropdown-panel .ng-option', '.ng-dropdown-panel [role="option"]', '.ng-option',
                '[data-screen]', '[routerlink]', 'td.clickable', '.btn'
            ];

            const elements = document.querySelectorAll(selectors.join(','));
            for (const el of elements) {
                // استبعاد أي عناصر تخص نافذة محادثة المساعد الذكي (LMS Copilot) حتى لا يضغط العميل على نفسه
                if (el.closest('lms-copilot-chat, .copilot-window, .ai-chat-window, .chat-panel')) {
                    continue;
                }

                // فحص الرؤية الحقيقية
                const style = window.getComputedStyle(el);
                if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') {
                    continue;
                }
                const rect = el.getBoundingClientRect();
                if (rect.width <= 0 || rect.height <= 0) continue;
                // التأكد من وجود العنصر داخل نافذة العرض
                if (rect.bottom < 0 || rect.top > window.innerHeight || rect.right < 0 || rect.left > window.innerWidth) {
                    continue;
                }

                const rawText = (el.innerText || el.textContent || el.getAttribute('aria-label') || el.getAttribute('title') || el.getAttribute('placeholder') || '').trim();
                const cleanText = rawText.replace(/\\s+/g, ' ').substring(0, 100);

                results.push({
                    tag: el.tagName.toLowerCase(),
                    text: cleanText,
                    x: Math.round(rect.left + rect.width / 2),
                    y: Math.round(rect.top + rect.height / 2),
                    rect: {
                        left: Math.round(rect.left),
                        top: Math.round(rect.top),
                        width: Math.round(rect.width),
                        height: Math.round(rect.height)
                    }
                });
            }
            return results;
        })();
        """
        try:
            items = await self.evaluate_script(ws_url, scanner_script)
            return items if isinstance(items, list) else []
        except Exception as e:
            logger.warn("Failed to extract interactive elements over CDP", error=str(e))
            return []

    async def wait_for_settle(self, ws_url: str, initial_url: str = "", max_wait_sec: float = 2.5) -> float:
        """
        انتظار ذكي لاستقرار الصفحة بعد كل نقرة أو تنقل (DOM-Settle Detection).
        المنطق:
        1. إذا تغير الـ URL → يعني التنقل تمّ، نبدأ فحص الاستقرار البنيوي.
        2. نقيس عدد العناصر التفاعلية مرتين بفاصل 150ms، إذا تساوى العددان → الصفحة مستقرة.
        3. حد أقصى صارم (max_wait_sec) لضمان عدم التوقف الأبدي.
        """
        start = time.perf_counter()
        deadline = start + max_wait_sec
        url_changed = False
        prev_element_count = -1

        while time.perf_counter() < deadline:
            await asyncio.sleep(0.12)
            try:
                curr_url = await self.evaluate_script(ws_url, "window.location.href")
                if initial_url and curr_url and curr_url != initial_url:
                    url_changed = True

                is_ready = await self.evaluate_script(ws_url, "document.readyState === 'complete'")
                if not is_ready:
                    continue

                # فحص استقرار عدد عناصر الـ DOM (DOM Element Count Stability)
                count_script = "document.querySelectorAll('button,a,input,select,ng-select,[role=\"button\"],[role=\"tab\"]').length"
                curr_count = await self.evaluate_script(ws_url, count_script)
                if isinstance(curr_count, int):
                    if curr_count == prev_element_count and (time.perf_counter() - start) >= 0.3:
                        break
                    prev_element_count = curr_count

                if url_changed and is_ready and (time.perf_counter() - start) >= 0.5:
                    break
            except Exception as e:
                logger.debug("wait_for_settle check tick error", error=str(e))

        elapsed = (time.perf_counter() - start) * 1000
        logger.debug("DOM settle completed", elapsed_ms=round(elapsed, 1), url_changed=url_changed)
        return elapsed

    async def click_element_or_coordinate(
        self,
        ws_url: str,
        x: int,
        y: int,
        target_text: str | None = None,
        interactive_elements: list[dict[str, Any]] | None = None,
    ) -> tuple[int, int, bool]:
        """
        تنفيذ نقرة ذكية منجذبة ذاتياً (DOM-Anchored Snapped Click):
        1. إذا وجد تطابق لنص العنصر المستهدف (target_text) مع عنصر تفاعلي حقيقي في الصفحة،
           تنجذب النقرة مباشرة إلى مركز العنصر الحقيقي بدقة 100%.
        2. إذا لم يوجد تطابق نصي، يتم فحص أقرب عنصر تفاعلي ضمن نطاق مسافة قريبة (Radius Snapping 35px).
        3. إذا لم يوجد، يتم النقر عند الإحداثيات [x, y] كـ Fallback.
        ترجع: (final_x, final_y, was_snapped)
        """
        elements = interactive_elements
        if elements is None and target_text:
            elements = await self.get_interactive_elements(ws_url)

        snapped = False
        target_x, target_y = x, y

        if elements:
            # محاولة 1: المطابقة بالنص (Semantic Arabic Normalized Match)
            if target_text:
                clean_target = target_text.strip().lower()
                for prefix in ["زر", "أيقونة", "قائمة", "خيار", "تبويب", "انقر على", "اضغط على", "الانتقال الى", "اذهب الى"]:
                    if clean_target.startswith(prefix):
                        clean_target = clean_target[len(prefix):].strip()

                norm_target = self.normalize_ar(clean_target)

                candidates = []
                for el in elements:
                    el_raw = el.get("text") or ""
                    norm_el = self.normalize_ar(el_raw)
                    if len(norm_el) >= 2 and len(norm_target) >= 2:
                        if norm_target in norm_el or norm_el in norm_target:
                            dist = ((el["x"] - x) ** 2 + (el["y"] - y) ** 2) ** 0.5
                            score = 0 if norm_target == norm_el else 1
                            candidates.append((score, dist, el))

                if candidates:
                    candidates.sort(key=lambda c: (c[0], c[1]))
                    best_el = candidates[0][2]
                    target_x = best_el["x"]
                    target_y = best_el["y"]
                    snapped = True
                    logger.info("DOM-Anchor snapped click by semantic text match", target=clean_target, matched_text=best_el.get("text"), x=target_x, y=target_y)

            # محاولة 2: إذا لم يتطابق النص ولكن الإحداثيات قريبة جداً من عنصر تفاعلي (Proximity Snap < 40px)
            if not snapped:
                best_dist = 40.0
                best_el = None
                for el in elements:
                    dist = ((el["x"] - x) ** 2 + (el["y"] - y) ** 2) ** 0.5
                    if dist < best_dist:
                        best_dist = dist
                        best_el = el

                if best_el:
                    target_x = best_el["x"]
                    target_y = best_el["y"]
                    snapped = True
                    logger.info("DOM-Anchor snapped click by proximity", dist=best_dist, element=best_el.get("text"), x=target_x, y=target_y)

        # تنفيذ النقر الفعلي عند الإحداثيات المنجذبة
        await self.click_at(ws_url, target_x, target_y)
        return target_x, target_y, snapped

    # endregion

    # ==============================================================================
    # region 4: ERP Host Navigation & Form Detection (التنقل الذكي وفتح الشاشات)
    # ==============================================================================

    async def navigate_to_erp_screen(self, ws_url: str, screen_id_or_name: Any) -> bool:
        """
        استدعاء مباشر لجسر ERP الداخلي للانتقال للشاشة المطلوبة في خطوة واحدة.
        window.DynamicERP.navigateToScreen(289)
        """
        script = f"""
        (async function() {{
            const target = {json.dumps(screen_id_or_name)};
            const targetPid = parseInt(target, 10);
            const targetStr = String(target).trim().toLowerCase();

            // 1. الأولوية الأولى: جسر DynamicERP الرسمي إن وجد
            if (window.DynamicERP && typeof window.DynamicERP.navigateToScreen === 'function') {{
                try {{
                    const res = window.DynamicERP.navigateToScreen(target);
                    if (res && typeof res.then === 'function') await res;
                    return true;
                }} catch(e) {{
                    console.warn('Bridge navigateToScreen error:', e);
                }}
            }}

            // 2. الأولوية الثانية: خدمة التنقل الأصلية للنظام (Angular app-base -> pageService)
            try {{
                const baseEl = document.querySelector('app-base');
                if (window.ng && window.ng.getComponent && baseEl) {{
                    const comp = window.ng.getComponent(baseEl);
                    const ps = comp ? comp.pageService : null;
                    if (ps && ps.pageAuthArray && ps.pageAuthArray.length > 0) {{
                        const pageAuth = ps.pageAuthArray.find(a => {{
                            const p = a.Page || {{}};
                            const pid = p.PageID || p.page_id;
                            const pName = (p.PageName || p.screen_key || '').trim().toLowerCase();
                            const arName = (p.ArName || p.name_ar || '').trim().toLowerCase();
                            return (targetPid && pid === targetPid) || pName === targetStr || arName === targetStr;
                        }});
                        if (pageAuth && pageAuth.Page) {{
                            comp.zone.run(() => {{
                                ps.addNewPage(pageAuth.Page);
                                comp.cdr.detectChanges();
                            }});
                            return true;
                        }}
                    }}
                }}
            }} catch(e) {{
                console.warn('Host Angular pageService navigation error:', e);
            }}

            // 3. الأولوية الثالثة: التوجيه بالرابط المباشر
            if (targetPid && !isNaN(targetPid)) {{
                try {{
                    window.location.href = `/core?p=${{targetPid}}&a=${{targetPid}}`;
                    return true;
                }} catch(e) {{}}
            }}

            return false;
        }})()
        """
        try:
            return bool(await self.evaluate_script(ws_url, script))
        except Exception as e:
            logger.warning("CDP Bridge navigateToScreen failed", error=str(e))
            return False

    async def get_user_authorized_screens(self, ws_url: str) -> list[dict[str, Any]]:
        """
        استدعاء مباشر لجسر window.DynamicERP.listUserPages() لجلب الشاشات المسموحة للمستخدم الحالي
        مباشرة من ذاكرة المتصفح مع اسم الموديول والاسم العربي والإنجليزي ورقم الصفحة.
        """
        script = """
        (function() {
            if (window.DynamicERP && typeof window.DynamicERP.listUserPages === 'function') {
                return window.DynamicERP.listUserPages();
            }
            if (window.DynamicERP && typeof window.DynamicERP.listScreens === 'function') {
                return window.DynamicERP.listScreens();
            }
            return [];
        })()
        """
        try:
            res = await self.evaluate_script(ws_url, script, timeout=8.0)
            return res if isinstance(res, list) else []
        except Exception as e:
            logger.warning("CDP Bridge get_user_authorized_screens failed", error=str(e))
            return []

    async def ensure_erp_form_open(self, ws_url: str, timeout_sec: float = 8.0) -> dict[str, Any]:
        """
        يضمن أن فورم الإدخال (AddOrEdit) مفتوح: bridge.triggerAddNew ثم زر "إضافة جديد" في الـ DOM مع انتظار الجاهزية.
        """
        script = """
        (async function() {
            const sleep = ms => new Promise(r => setTimeout(r, ms));
            const ctxOpen = () => { try { const c = window.DynamicERP?.getActiveFormContext?.(); return !!(c && (c.dataObject || (c.rows && c.formType !== 'dom') || c.isInvoice)); } catch(e) { return false; } };
            const domOpen = () => {
                const p = document.querySelector('.dp-shell__pages > div:not([hidden])') || document;
                const f = p.querySelector('.dp-edit, .dp-list__pre, .dp-edit__head, section.dp-pu__sup, app-add-or-edit, .dp-modal, #addOrEditPopUp');
                if (f && f.offsetParent !== null) return true;
                const primaryInp = p.querySelector('[formcontrolname="SupplierID"], [formcontrolname="CustomerID"], [formcontrolname="StoreID"], [formcontrolname="EmpId"], input#productQty');
                return !!(primaryInp && primaryInp.offsetParent !== null);
            };
            const isOpen = () => ctxOpen() || domOpen();
            if (isOpen()) return { opened: true, method: 'already_open' };
            const deadline = Date.now() + __TIMEOUT_MS__;
            let bridgeCalls = 0, domClicks = 0;
            while (Date.now() < deadline) {
                try { if (window.DynamicERP && typeof window.DynamicERP.triggerAddNew === 'function') { bridgeCalls++; await window.DynamicERP.triggerAddNew(); } } catch(e) {}
                await sleep(350);
                if (isOpen()) return { opened: true, method: 'bridge', bridgeCalls, domClicks };
                const page = document.querySelector('.dp-shell__pages > div:not([hidden])') || document;
                const masterBtn = page.querySelector('button.dp-btn--primary.dp-list__act, .dp-list__act.dp-btn--primary, button.dp-btn--new, [data-action="new"], button.dp-list__act');
                const btn = masterBtn || Array.from(page.querySelectorAll('button, a')).find(b => {
                    if (b.closest('lms-ai-copilot, app-copilot-chat, nav, .dp-hdr')) return false;
                    const txt = (b.textContent || '').trim().replace(/[إأآ]/g, 'ا');
                    const hasPlus = !!b.querySelector('.fa-plus, .bi-plus, i[class*="plus"]');
                    return /اضافة جديد|جديد|^اضافة$|add new/i.test(txt) || (hasPlus && (/اضاف|جديد/.test(txt) || txt === ''));
                });
                if (btn && btn.offsetParent !== null) { 
                    domClicks++; 
                    btn.click(); 
                    await sleep(550); 
                    if (isOpen()) return { opened: true, method: 'dom_button', bridgeCalls, domClicks }; 
                }
                await sleep(250);
            }
            return { opened: false, method: 'timeout', bridgeCalls, domClicks };
        })()
        """.replace("__TIMEOUT_MS__", str(int(timeout_sec * 1000)))
        try:
            res = await self.evaluate_script(ws_url, script, timeout=timeout_sec + 6.0)
            return res if isinstance(res, dict) else {"opened": bool(res), "method": "raw"}
        except Exception as e:
            logger.error("ensure_erp_form_open failed", error=str(e))
            return {"opened": False, "method": "error", "error": str(e)}

    # endregion

    # ==============================================================================
    # region 5: Polymorphic Form Filling & Auto-Cataloging (محرك التعبئة والاستكشاف)
    # ==============================================================================

    async def fill_erp_form_bridge(self, ws_url: str, payload: dict[str, Any]) -> dict[str, Any]:
        """
        حقن وتعبئة الفاتورة وجدول الأصناف مباشرة عبر جسر window.DynamicERP.fillFormData(payload)
        أو عبر استدعاء محرك التعبئة المباشر فائق الدقة.
        """
        payload_json = json.dumps(payload, ensure_ascii=False)
        script = f"""
        (async function() {{
            const payload = {payload_json};
            const logs = [];

            // 1. محرك التعبئة المعمم فائق الدقة (Generic Polymorphic DOM Injector)
            async function selectNgSelect(target, targetVal) {{
                if (!targetVal) return false;
                const sel = typeof target === 'string' ? document.querySelector(target) : target;
                if (!sel) return false;
                const container = sel.querySelector('.ng-select-container') || sel;
                container.click();
                await new Promise(r => setTimeout(r, 120));
                const input = sel.querySelector('input');
                if (input) {{
                    input.focus();
                    input.value = targetVal;
                    input.dispatchEvent(new Event('input', {{ bubbles: true }}));
                }}
                await new Promise(r => setTimeout(r, 450));
                const panels = Array.from(document.querySelectorAll('body > ng-dropdown-panel, ng-dropdown-panel, .ng-dropdown-panel'));
                const lastPanel = panels[panels.length - 1];
                if (!lastPanel) return false;
                const opts = Array.from(lastPanel.querySelectorAll('.ng-option, [role="option"]'));
                const norm = s => String(s || '').trim().replace(/[أإآ]/g, 'ا').replace(/ى/g, 'ي');
                const tv = norm(targetVal);
                const tvStem = tv.replace(/[ةه]$/, '');
                const wantsNeg = tv.includes('غير');
                const okOpts = opts.filter(o => wantsNeg || !norm(o.textContent).includes('غير'));
                const match = okOpts.find(o => norm(o.textContent) === tv)
                    || okOpts.find(o => norm(o.textContent).includes(tv))
                    || okOpts.find(o => tvStem.length >= 3 && norm(o.textContent).includes(tvStem));
                if (match) {{
                    match.click();
                    return true;
                }}
                if (input) {{
                    input.dispatchEvent(new KeyboardEvent('keydown', {{ bubbles: true, key: 'Escape' }}));
                }}
                return false;
            }}

            function findFieldElement(fieldName) {{
                const candidates = [
                    `[formcontrolname='${{fieldName}}']`,
                    `[formcontrolname='${{fieldName.toLowerCase()}}']`,
                    `#${{fieldName}}`,
                    `#${{fieldName.toLowerCase()}}`,
                    `input[name='${{fieldName}}']`,
                    `select[name='${{fieldName}}']`,
                    `textarea[name='${{fieldName}}']`
                ];
                for (const c of candidates) {{
                    const el = document.querySelector(c);
                    if (el) return el;
                }}

                // المطابقة المعممة بواسطة تسميات الحقول بالعربية أو الإنجليزية (Label-Anchored Matching)
                try {{
                    const labels = Array.from(document.querySelectorAll('label'));
                    const cleanField = fieldName.trim().toLowerCase();
                    const matchedLabel = labels.find(l => {{
                        const txt = (l.textContent || '').trim().toLowerCase();
                        return txt && (txt === cleanField || txt.includes(cleanField) || cleanField.includes(txt));
                    }});
                    if (matchedLabel) {{
                        const forAttr = matchedLabel.getAttribute('for');
                        if (forAttr) {{
                            const target = document.getElementById(forAttr);
                            if (target) return target;
                        }}
                        const parent = matchedLabel.closest('.form-group, .col, .field, div, td, tr');
                        if (parent) {{
                            const inner = parent.querySelector('input:not([type="hidden"]), select, textarea, ng-select');
                            if (inner) return inner;
                        }}
                    }}
                }} catch(e) {{
                    console.warn('Label match error:', e);
                }}

                return null;
            }}

            async function fillSingleControl(fieldName, val) {{
                if (val === undefined || val === null || val === '') return false;
                const el = findFieldElement(fieldName);
                if (!el) return false;

                const isNgSelect = el.tagName.toLowerCase() === 'ng-select' || el.classList.contains('ng-select');
                if (isNgSelect) {{
                    const strVal = String(val);
                    const firstTerm = strVal.includes(' ') ? strVal.split(' ')[0] : strVal;
                    return await selectNgSelect(el, strVal) || await selectNgSelect(el, firstTerm);
                }}

                if (el.type === 'checkbox') {{
                    el.checked = Boolean(val);
                    el.dispatchEvent(new Event('change', {{ bubbles: true }}));
                    return true;
                }}

                el.focus();
                el.value = val;
                el.dispatchEvent(new Event('input', {{ bubbles: true }}));
                el.dispatchEvent(new Event('change', {{ bubbles: true }}));
                await new Promise(r => setTimeout(r, 80));
                return true;
            }}

            // أ. تعبئة حقول الهيدر ديناميكياً لأي وثيقة
            const header = payload.header || {{}};
            let filledCount = 0;
            const deferredTotals = [];
            for (const [key, val] of Object.entries(header)) {{
                const sVal = String(val).toUpperCase();
                const lKey = key.toLowerCase();
                const isTotalVal = sVal === '$TOTAL' || sVal === 'TOTAL';
                const isPaidField = lKey.includes('popaid') || lKey.includes('cashpaid') || lKey.includes('madfou') || /مدفوع|محصل|سداد|نقد/.test(key);
                if (isTotalVal || (isPaidField && (isTotalVal || !val || val === '0' || Number(val) === 0))) {{
                    deferredTotals.push(key);
                    continue;
                }}
                if (await fillSingleControl(key, val)) {{
                    filledCount++;
                }}
            }}

            // ب. تعبئة أسطر الجدول / الأصناف ديناميكياً لأي وثيقة
            const items = payload.items || payload.lines || [];
            let itemsAdded = 0;
            for (const item of items) {{
                let itemFilled = false;

                const prodSel = document.querySelector('ng-select#product, [formcontrolname="product"], [formcontrolname="AccID"], ng-select#AccID, table ng-select');
                const itemName = item.product || item.name || item.AccID || item.ItemName;
                if (prodSel && itemName) {{
                    if (await selectNgSelect(prodSel, itemName)) {{
                        itemFilled = true;
                    }}
                }}

                for (const [col, colVal] of Object.entries(item)) {{
                    if (col !== 'product' && col !== 'name' && col !== 'AccID' && col !== 'ItemName') {{
                        if (await fillSingleControl(col, colVal)) {{
                            itemFilled = true;
                        }}
                    }}
                }}

                await new Promise(r => setTimeout(r, 350));
                const qtyInp = document.querySelector('input#productQty, [formcontrolname="productQty"], input[type="number"]');
                const continueBtn = Array.from(document.querySelectorAll('button')).find(b => {{
                    const t = (b.textContent || '').trim();
                    return t === 'متابعة' || t === 'تأكيد' || t === 'موافق' || t === 'إضافة';
                }});
                if (qtyInp && continueBtn && (item.productQty !== undefined || item.qty !== undefined)) {{
                    const qVal = item.productQty !== undefined ? item.productQty : item.qty;
                    qtyInp.focus();
                    qtyInp.value = qVal;
                    qtyInp.dispatchEvent(new Event('input', {{ bubbles: true }}));
                    qtyInp.dispatchEvent(new Event('change', {{ bubbles: true }}));
                    await new Promise(r => setTimeout(r, 120));
                    continueBtn.click();
                    await new Promise(r => setTimeout(r, 300));
                }}

                if (itemFilled) itemsAdded++;
            }}

            // ج. تسوية الدفع: المحصل نقداً = إجمالي الفاتورة المحسوب بعد إدخال الأصناف
            let paidFilled = false;
            if (deferredTotals.length) {{
                await new Promise(r => setTimeout(r, 450));
                let total = null;
                try {{
                    const dobj = (window.DynamicERP.getActiveFormContext() || {{}}).dataObject || {{}};
                    total = dobj.TotalCurrancy || dobj.TotalOrderBeforCurrancy || dobj.NetTotal || null;
                }} catch(e) {{}}

                if (!total || Number(total) === 0) {{
                    const grandValEl = document.querySelector('.dp-edit__grandval, .dp-edit__grand strong, .dp-edit__grand, [class*="grandval"]');
                    if (grandValEl) {{
                        const v = parseFloat((grandValEl.textContent || '').replace(/,/g, '').replace(/[^0-9.]/g, '').trim());
                        if (!isNaN(v) && v > 0) {{ total = v; }}
                    }}
                }}

                if (!total || Number(total) === 0) {{
                    const totInputs = Array.from(document.querySelectorAll('input#TotalCurrancy, input[name="TotalCurrancy"], input[formcontrolname="TotalCurrancy"], input#TotalOrderBeforCurrancy, input[formcontrolname="TotalOrderBeforCurrancy"], .dp-edit__total input[readonly], .totlbl + * input, input[name*="total" i]'));
                    for (const inp of totInputs) {{
                        const v = parseFloat((inp.value || '').replace(/,/g, ''));
                        if (!isNaN(v) && v > 0) {{ total = v; break; }}
                    }}
                }}

                if (!total || Number(total) === 0) {{
                    let sum = 0;
                    for (const itm of items) {{
                        const q = parseFloat(itm.productQty ?? itm.qty ?? itm.quantity ?? 1) || 1;
                        const p = parseFloat(itm.price ?? itm.cost ?? itm.UnitPrice ?? itm.ItemPrice ?? 0) || 0;
                        sum += q * p;
                    }}
                    if (sum > 0) total = sum;
                }}

                if (total) {{
                    const paidDirect = document.querySelector('input#POPaid, input[name="POPaid"], input[formcontrolname="POPaid"], input#POPaidCurrancy, input[name="POPaidCurrancy"], input[formcontrolname="POPaidCurrancy"], input[name*="paid" i], input[id*="paid" i]');
                    const lbls = Array.from(document.querySelectorAll('.dp-edit__totlbl, .totlbl, [class*="totlbl"], label'));
                    const lbl = lbls.find(l => /المحصل|مدفوع|المسدد|نقد|سداد/.test(l.textContent || ''));
                    const holder = lbl ? (lbl.closest('li, .dp-edit__total, .dp-field, .form-group') || lbl.parentElement) : null;
                    const inp = paidDirect || (holder ? holder.querySelector('input:not([disabled]):not([readonly])') : null);

                    if (inp) {{
                        const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                        inp.focus();
                        setter.call(inp, String(total));
                        inp.dispatchEvent(new Event('input', {{ bubbles: true }}));
                        inp.dispatchEvent(new Event('change', {{ bubbles: true }}));
                        inp.dispatchEvent(new Event('blur', {{ bubbles: true }}));
                        paidFilled = true;
                    }}

                    if (window.DynamicERP && typeof window.DynamicERP.fillFormData === 'function') {{
                        try {{
                            const bRes = await window.DynamicERP.fillFormData({{
                                fields: {{ POPaidCurrancy: total, POPaid: total }},
                                rows: []
                            }});
                            if (bRes) paidFilled = true;
                        }} catch(e) {{}}
                    }}

                    try {{
                        const ctx = window.DynamicERP?.getActiveFormContext?.();
                        if (ctx && ctx.dataObject) {{
                            ctx.dataObject.POPaidCurrancy = total;
                            ctx.dataObject.POPaid = total;
                            paidFilled = true;
                        }}
                    }} catch(e) {{}}
                }}
                if (paidFilled) filledCount++;
            }}

            return {{
                success: filledCount > 0 || itemsAdded > 0,
                method: 'dom_precision_generic',
                filled_count: filledCount,
                items_count: itemsAdded,
                paid_filled: paidFilled
            }};
        }})()
        """
        try:
            res = await self.evaluate_script(ws_url, script, timeout=25.0)
            return res if isinstance(res, dict) else {"success": bool(res), "method": "bridge_raw"}
        except Exception as e:
            logger.error("Failed to execute bridge/precision form fill", error=str(e))
            return {"success": False, "error": str(e)}

    async def snapshot_form_state(self, ws_url: str) -> dict[str, Any]:
        """
        لقطة اكتشاف ذاتي من الـ ERP نفسه: كل حقول الإدخال (بما فيها الفوتر) + مفاتيح/قيم dataObject الحقيقية،
        لتُسجَّل في لوج الجلسة وتُستخدم في ضبط الربط.
        """
        script = """
        (function() {
            try {
                const page = document.querySelector('.dp-shell__pages > div:not([hidden])') || document;
                const inputs = Array.from(page.querySelectorAll('input, select, textarea, ng-select')).slice(0, 120).map(el => {
                    const holder = el.closest('li, .dp-edit__total, .dp-field, .form-group, [class*="col-"]') || el.parentElement;
                    const lbl = holder ? holder.querySelector('label, .dp-edit__totlbl, .totlbl, mat-label') : null;
                    return {
                        tag: el.tagName.toLowerCase(), type: el.type || '',
                        name: el.getAttribute('name') || el.getAttribute('formcontrolname') || el.id || '',
                        label: lbl ? (lbl.textContent || '').trim().slice(0, 40) : '',
                        disabled: !!(el.disabled || el.readOnly)
                    };
                });
                let model = {}, isOpen = false, formType = null;
                try {
                    const c = window.DynamicERP.getActiveFormContext() || {};
                    isOpen = !!c.isOpen; formType = c.formType || null;
                    for (const [k, v] of Object.entries(c.dataObject || {})) { if (v === null || typeof v !== 'object') model[k] = v; }
                } catch(e) {}
                const totals = Array.from(page.querySelectorAll('.dp-edit__totlbl, [class*="totlbl"]')).map(l => (l.textContent || '').trim()).slice(0, 20);
                return { isOpen, formType, inputs, totals, model };
            } catch(e) { return { error: String(e) }; }
        })()
        """
        try:
            res = await self.evaluate_script(ws_url, script, timeout=10.0)
            return res if isinstance(res, dict) else {}
        except Exception as e:
            logger.error("snapshot_form_state failed", error=str(e))
            return {"error": str(e)}

    async def get_active_screen_metadata(self, ws_url: str) -> list[dict[str, Any]]:
        """
        استخراج ميتاداتا الشاشة النشطة لحظياً (0ms) مباشرة من ذاكرة Angular (RxJS columnList BehaviorSubject)
        طبقاً لمواصفات ERP_METADATA_DISCOVERY_REFERENCE.md.
        تعيد الحقول المرئية والإلزامية مع ColumnName و arColumnLabel و InsertType و IsGeneral (Header vs Grid)
        ومصدر القوائم DroModel بدون الحاجة للـ DOM scraping أو استدعاءات SQL/API.
        """
        script = """
        (function() {
            try {
                let columns = [];
                // 1. محاولة الوصول عبر الجسر الرسمي
                if (window.DynamicERP && typeof window.DynamicERP.getActiveComponentInstance === 'function') {
                    const comp = window.DynamicERP.getActiveComponentInstance();
                    if (comp && comp.columnList && typeof comp.columnList.getValue === 'function') {
                        columns = comp.columnList.getValue() || [];
                    }
                }

                // 2. محاولة الوصول المباشر عبر شجرة مكونات Angular إذا لم يكن الجسر متاحاً
                if (!columns || columns.length === 0) {
                    const pageEl = document.querySelector('.dp-shell__pages > div:not([hidden]), app-base');
                    if (window.ng && window.ng.getComponent && pageEl) {
                        const comp = window.ng.getComponent(pageEl);
                        if (comp && comp.columnList && typeof comp.columnList.getValue === 'function') {
                            columns = comp.columnList.getValue() || [];
                        }
                    }
                }

                if (!Array.isArray(columns) || columns.length === 0) {
                    return [];
                }

                return columns
                    .filter(c => c.InsertVisable === 1 || c.IsRquired === 1)
                    .map(c => ({
                        name: c.ColumnName,
                        label: c.arColumnLabel || c.enColumnLabel || c.ColumnName,
                        type: c.InsertType || 'text',
                        isMandatory: Boolean(c.IsRquired),
                        isHeader: Boolean(c.IsGeneral),
                        lookup: c.DroModel || null,
                        sort: c.sort || 0
                    }))
                    .sort((a, b) => a.sort - b.sort);
            } catch(e) {
                return [];
            }
        })()
        """
        try:
            res = await self.evaluate_script(ws_url, script, timeout=8.0)
            return res if isinstance(res, list) else []
        except Exception as e:
            logger.debug("get_active_screen_metadata failed", error=str(e))
            return []

    async def inspect_active_page_dom(self, ws_url: str) -> dict[str, Any]:
        """
        فحص الـ DOM المباشر للشاشة المفتوحة حالياً في المتصفح لاستخراج جميع عناصر Angular
        والـ formControls والتسميات العربية والجداول تلقائياً (Self-Discovery Engine).
        """
        script = """
        (function() {
            try {
                const url = window.location.href;
                const match = url.match(/page_id=(\\d+)/i) || url.match(/\\/(\\d+)(?:[?#]|$)/) || url.match(/#\\/[^\\/]+\\/(\\d+)/);
                const pageId = match ? parseInt(match[1]) : null;

                const headerEl = document.querySelector('h1, h2, h3, .page-title, .breadcrumb-item.active');
                const pageTitle = headerEl ? (headerEl.textContent || '').trim() : document.title;

                const controls = [];
                const elements = Array.from(document.querySelectorAll('[formcontrolname], input:not([type="hidden"]), select, textarea, ng-select'));
                const seenNames = new Set();

                for (const el of elements) {
                    const fcName = el.getAttribute('formcontrolname') || el.getAttribute('name') || el.id;
                    if (!fcName || seenNames.has(fcName.toLowerCase())) continue;
                    seenNames.add(fcName.toLowerCase());

                    let label = '';
                    if (el.id) {
                        const lbl = document.querySelector(`label[for="${el.id}"]`);
                        if (lbl) label = (lbl.textContent || '').trim();
                    }
                    if (!label) {
                        const parent = el.closest('.form-group, .col, .field, div');
                        if (parent) {
                            const lbl = parent.querySelector('label');
                            if (lbl) label = (lbl.textContent || '').trim();
                        }
                    }
                    if (!label) {
                        label = el.getAttribute('placeholder') || el.getAttribute('title') || fcName;
                    }

                    let type = el.tagName.toLowerCase();
                    if (type === 'input') type = el.type || 'text';
                    if (el.classList.contains('ng-select') || type === 'ng-select') type = 'select_typeahead';

                    controls.push({
                        name: fcName,
                        label: label,
                        type: type,
                        required: el.hasAttribute('required') || el.getAttribute('aria-required') === 'true'
                    });
                }

                const grids = [];
                const tables = Array.from(document.querySelectorAll('table'));
                for (const table of tables) {
                    const headers = Array.from(table.querySelectorAll('thead th, tr:first-child th'))
                        .map(th => (th.textContent || '').trim())
                        .filter(Boolean);
                    if (headers.length >= 2) {
                        grids.push({ headers: headers });
                    }
                }

                return {
                    page_id: pageId,
                    url: url,
                    title: pageTitle,
                    controls_count: controls.length,
                    controls: controls,
                    grids: grids
                };
            } catch(e) {
                return { error: String(e) };
            }
        })()
        """
        try:
            res = await self.evaluate_script(ws_url, script, timeout=12.0)
            return res if isinstance(res, dict) else {}
        except Exception as e:
            logger.error("Failed to inspect active page DOM", error=str(e))
            return {"error": str(e)}

    async def auto_catalog_active_page(self, ws_url: str, persist: bool = False) -> dict[str, Any]:
        """
        فحص وتسجيل الشاشة الحالية في المتصفح الحي تلقائياً في كتالوج النماذج
        (Self-Learning Auto-Cataloging on Live Navigation).
        """
        from src.services.forms_catalog_service import forms_catalog_service

        inspection = await self.inspect_active_page_dom(ws_url)
        if not inspection or "error" in inspection or not inspection.get("page_id"):
            logger.warning("Auto-catalog inspection skipped: no valid page_id found", inspection=inspection)
            return {}

        registered = forms_catalog_service.auto_register_from_dom_inspection(inspection, persist=persist)
        logger.info(
            "Auto-cataloged active screen successfully",
            page_id=registered.get("page_id"),
            title=registered.get("name_ar"),
            controls=len(registered.get("header_fields", {})),
        )
        return registered

    # endregion


# Singleton instance
cdp_agent_service = CdpAgentService()

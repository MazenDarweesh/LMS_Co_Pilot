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
            except Exception:
                pass

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
                except Exception:
                    pass

    @staticmethod
    def normalize_ar(s: str) -> str:
        """تطبيع النصوص العربية لإزالة فروق الهمزات والتاء المربوطة وحروف العطف والمسافات"""
        import re
        if not s:
            return ""
        s = re.sub(r"[أإآ]", "ا", s)
        s = re.sub(r"ة", "ه", s)
        s = re.sub(r"[\s_\-و]+", "", s).lower()
        return s

    async def get_page_state(self, ws_url: str) -> dict[str, Any]:
        """استخراج حالة الصفحة الحالية: الرابط، العنوان، والنصوص البارزة في الترويسات"""
        script = """
        (function() {
            const headings = [];
            document.querySelectorAll('h1, h2, h3, .dp-list__ttl, .dp-hdr__tab--active, .active').forEach(el => {
                const txt = (el.innerText || el.textContent || '').trim();
                if (txt && txt.length < 100) headings.push(txt);
            });
            return {
                url: window.location.href,
                title: document.title,
                headings: headings.slice(0, 5)
            };
        })()
        """
        try:
            res = await self.evaluate_script(ws_url, script)
            if isinstance(res, dict):
                return res
        except Exception as e:
            logger.warn("Failed to get page state", error=str(e))
        return {"url": "", "title": "", "headings": []}

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

    async def wait_for_settle(self, ws_url: str, initial_url: str = "", max_wait_sec: float = 0.8) -> float:
        """
        انتظار ذكي لاستقرار الصفحة وتغير المسار أو جاهزية الـ DOM بدلاً من فترات الانتظار الثابتة (sleep).
        يتحقق كل 50ms ويعود فور تغير الرابط أو اكتمال التحميل لتقليل الـ Latency إلى الحد الأدنى.
        """
        import time
        start = time.perf_counter()
        deadline = start + max_wait_sec

        while time.perf_counter() < deadline:
            await asyncio.sleep(0.05)
            try:
                curr_url = await self.evaluate_script(ws_url, "window.location.href")
                if initial_url and curr_url and curr_url != initial_url:
                    break
                is_ready = await self.evaluate_script(ws_url, "document.readyState === 'complete'")
                if is_ready and (time.perf_counter() - start) >= 0.15:
                    break
            except Exception:
                pass
        return (time.perf_counter() - start) * 1000

    async def click_element_or_coordinate(
        self,
        ws_url: str,
        x: int,
        y: int,
        target_text: Optional[str] = None,
        interactive_elements: Optional[list[dict[str, Any]]] = None,
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

                # البحث عن أفضل مطابقة مع تفضيل العناصر غير الفارغة والأقرب
                candidates = []
                for el in elements:
                    el_raw = el.get("text") or ""
                    norm_el = self.normalize_ar(el_raw)
                    # شرط أساسي: أن يكون النص غير تافه (أطول من حرفين)
                    if len(norm_el) >= 2 and len(norm_target) >= 2:
                        if norm_target in norm_el or norm_el in norm_target:
                            dist = ((el["x"] - x) ** 2 + (el["y"] - y) ** 2) ** 0.5
                            # مطابقة تامة للنص تحظى بأعلى أولوية
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

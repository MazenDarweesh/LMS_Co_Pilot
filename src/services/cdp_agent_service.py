"""
CDP (Chrome DevTools Protocol) Agent Service.
Enables autonomous AI Vision Agent execution directly inside the user's active browser window.
Eliminates session/login friction by connecting to Chrome/Edge via CDP WebSocket (default port 9222).
"""

import asyncio
import json
from pathlib import Path
import re
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

        # التعامل الآلي الصارم مع أنفاق مايكروسوفت السحابية DevTunnels (Task A.4)
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

    async def is_cdp_available(self, port: Optional[int] = None, host: str = "127.0.0.1") -> bool:
        """فحص ما إذا كان المتصفح يعمل مع منفذ تصحيح الأخطاء المفتوح مع إعادة المحاولة للأنفاق السحابية (Task A.6)"""
        p = port or self.default_port
        h = host or "127.0.0.1"
        base_http, _ = self._resolve_urls(h, p)
        for attempt in range(2):
            try:
                async with httpx.AsyncClient(timeout=3.0, verify=False) as client:
                    res = await client.get(f"{base_http}/json/version")
                    if res.status_code == 200:
                        return True
            except Exception:
                if attempt == 0:
                    await asyncio.sleep(0.35)
        return False

    async def ensure_cdp_available(self, port: Optional[int] = None, host: str = "127.0.0.1") -> bool:
        """
        فحص توفر منفذ تصحيح الأخطاء، وإذا كان الاتصال محلياً والمنفذ مغلقاً،
        يقوم تلقائياً بتشغيل متصفح Chrome بمنفذ تصحيح الأخطاء 9222 وبروفايل معزول لضمان عمل الوكيل فوراً بدون أوامر يدوية.
        """
        p = port or self.default_port
        h = host or "127.0.0.1"
        if await self.is_cdp_available(p, h):
            return True

        clean_h = h.lower().replace("http://", "").replace("https://", "").split(":")[0]
        if clean_h in ("127.0.0.1", "localhost"):
            logger.info("Local Chrome CDP offline; auto-spawning Chrome with remote debugging...", port=p)
            try:
                import subprocess, shutil, sys, os
                chrome_candidates = [
                    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                    shutil.which("chrome"),
                ]
                chrome_path = next((c for c in chrome_candidates if c and os.path.exists(c)), None)
                if chrome_path:
                    user_data = r"C:\chrome-dev-profile"
                    os.makedirs(user_data, exist_ok=True)
                    cmd = [
                        chrome_path,
                        f"--remote-debugging-port={p}",
                        "--remote-debugging-address=0.0.0.0",
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

    async def get_active_erp_tab(self, port: Optional[int] = None, host: str = "127.0.0.1", title_match: str = "") -> Optional[dict[str, Any]]:
        """
        البحث عن التبويب النشط لنظام DynamicPro ERP واستخراج عنوان الـ WebSocket للتصحيح مع إعادة المحاولة.
        """
        p = port or self.default_port
        h = host or "127.0.0.1"
        base_http, base_ws = self._resolve_urls(h, p)
        for attempt in range(2):
            try:
                async with httpx.AsyncClient(timeout=4.0, verify=False) as client:
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
                        except Exception:
                            pass

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
            except Exception:
                if attempt == 0:
                    await asyncio.sleep(0.35)
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
        """استخراج حالة الصفحة الحالية: الرابط، العنوان، النصوص البارزة، والشاشة النشطة حالياً عبر الجسر"""
        script = """
        (function() {
            const headings = [];
            document.querySelectorAll('h1, h2, h3, .dp-list__ttl, .dp-hdr__tab--active, .active').forEach(el => {
                const txt = (el.innerText || el.textContent || '').trim();
                if (txt && txt.length < 100) headings.push(txt);
            });
            const activeScreen = (window.DynamicERP && typeof window.DynamicERP.getActiveScreen === 'function')
                ? window.DynamicERP.getActiveScreen()
                : null;
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

    async def evaluate_script(self, ws_url: str, script: str, timeout: float = 15.0) -> Any:
        """تنفيذ كود JavaScript في سياق التبويب واسترجاع القيمة"""
        res = await self.execute_cdp_command(
            ws_url,
            "Runtime.evaluate",
            {"expression": script, "returnByValue": True, "awaitPromise": True},
            timeout=timeout,
        )
        return res.get("result", {}).get("value")

    async def navigate_to_erp_screen(self, ws_url: str, screen_id_or_name: Any) -> bool:
        """
        استدعاء مباشر لجسر ERP الداخلي للانتقال للشاشة المطلوبة في خطوة واحدة.
        window.DynamicERP.navigateToScreen(289)
        """
        script = f"""
        (async function() {{
            if (window.DynamicERP && typeof window.DynamicERP.navigateToScreen === 'function') {{
                try {{
                    const res = window.DynamicERP.navigateToScreen({json.dumps(screen_id_or_name)});
                    if (res && typeof res.then === 'function') await res;
                    return true;
                }} catch(e) {{
                    console.error('Bridge navigateToScreen error:', e);
                    return false;
                }}
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

            // 1. الأولوية الأولى: جسر DynamicERP المدمج إن وجد
            if (window.DynamicERP && typeof window.DynamicERP.fillFormData === 'function') {{
                try {{
                    const bridgePayload = {{
                        fields: payload.header || {{}},
                        rows: payload.items || []
                    }};
                    const res = window.DynamicERP.fillFormData(bridgePayload);
                    const success = (res && typeof res.then === 'function') ? await res : res;
                    if (success) {{
                        return {{
                            success: true,
                            method: 'bridge',
                            detail: 'Filled via window.DynamicERP.fillFormData'
                        }};
                    }}
                }} catch(e) {{
                    console.warn('Bridge fillFormData failed, falling back:', e);
                }}
            }}

            // 2. محرك التعبئة المعمم فائق الدقة (Generic Polymorphic DOM Injector - Task B.3 & A.1.2)
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
                const match = opts.find(o => (o.textContent || '').trim().includes(targetVal)) || opts[0];
                if (match) {{
                    match.click();
                    return true;
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
                // تتيح تعبئة أي حقل في أي شاشة من الـ 821 شاشة حتى لو اختلف اسم الـ formControl
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
            for (const [key, val] of Object.entries(header)) {{
                if (await fillSingleControl(key, val)) {{
                    filledCount++;
                }}
            }}

            // ب. تعبئة أسطر الجدول / الأصناف ديناميكياً لأي وثيقة
            const items = payload.items || payload.lines || [];
            let itemsAdded = 0;
            for (const item of items) {{
                let itemFilled = false;

                // إذا كان هناك مدخل صنف ng-select
                const prodSel = document.querySelector('ng-select#product, [formcontrolname="product"], [formcontrolname="AccID"], ng-select#AccID, table ng-select');
                const itemName = item.product || item.name || item.AccID || item.ItemName;
                if (prodSel && itemName) {{
                    if (await selectNgSelect(prodSel, itemName)) {{
                        itemFilled = true;
                    }}
                }}

                // تعبئة باقي الحقول في السطر (مثل الكمية والسعر والمدين والدائن)
                for (const [col, colVal] of Object.entries(item)) {{
                    if (col !== 'product' && col !== 'name' && col !== 'AccID' && col !== 'ItemName') {{
                        if (await fillSingleControl(col, colVal)) {{
                            itemFilled = true;
                        }}
                    }}
                }}

                // معالجة المودال التلقائي للكمية أو التأكيد إن ظهر
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

            return {{
                success: filledCount > 0 || itemsAdded > 0,
                method: 'dom_precision_generic',
                filled_count: filledCount,
                items_count: itemsAdded
            }};
        }})()
        """
        try:
            res = await self.evaluate_script(ws_url, script, timeout=25.0)
            return res if isinstance(res, dict) else {"success": bool(res), "method": "bridge_raw"}
        except Exception as e:
            logger.error("Failed to execute bridge/precision form fill", error=str(e))
            return {"success": False, "error": str(e)}

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


# Singleton instance
cdp_agent_service = CdpAgentService()

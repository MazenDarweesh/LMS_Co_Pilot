"""
CDP Visual Grounding & DOM Inspection Service.
Handles screenshots with chat masking, DOM element coordinates extraction,
Arabic text normalization, DOM stability settle detection, and auto-snapped clicking.
"""

import asyncio
import re
import time
from typing import Any
import structlog

from src.services.cdp.input_dispatcher import CdpInputDispatcher
from src.services.cdp.script_loader import get_script

logger = structlog.get_logger()


class CdpVisualGrounding:
    """
    مسؤول عن الرصد البصري، التقاط الشاشة، قراءة مقاييس الـ Viewport،
    تطبيع النصوص العربية، وفحص استقرار الـ DOM والتأكد من هبوط النقرات في الأماكن الصحيحة.
    """

    def __init__(self, dispatcher: CdpInputDispatcher) -> None:
        self.dispatcher = dispatcher

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

    async def capture_screenshot(
        self, ws_url: str, quality: int = 80, mask_chat: bool = True
    ) -> str:
        """
        التقاط لقطة شاشة للتبويب وإرجاعها كـ Base64 JPEG مضغوطة وسريعة للرؤية البصرية.
        مع إخفاء نافذة المساعد الذكي لحظياً أثناء اللقطة حتى لا تشتت الرؤية وتسبب محاولات إغلاق وهمية.
        """
        if mask_chat:
            try:
                await self.dispatcher.evaluate_script(
                    ws_url,
                    """document.querySelectorAll('lms-copilot-chat, .ai-chat-window, .copilot-window').forEach(el => el.style.visibility = 'hidden');""",
                )
            except Exception as e:
                logger.debug("Failed to mask chat window before screenshot", error=str(e))

        try:
            res = await self.dispatcher.execute_cdp_command(
                ws_url,
                "Page.captureScreenshot",
                {"format": "jpeg", "quality": quality, "captureBeyondViewport": False},
                timeout=8.0,
            )
            return res.get("data", "")
        finally:
            if mask_chat:
                try:
                    await self.dispatcher.evaluate_script(
                        ws_url,
                        """document.querySelectorAll('lms-copilot-chat, .ai-chat-window, .copilot-window').forEach(el => el.style.visibility = '');""",
                    )
                except Exception as e:
                    logger.debug("Failed to unmask chat window after screenshot", error=str(e))

    async def get_page_state(self, ws_url: str) -> dict[str, Any]:
        """استخراج حالة الصفحة الحالية: الرابط، العنوان، النصوص البارزة، والشاشة النشطة حالياً عبر الجسر"""
        script = get_script("page_state.js")
        try:
            res = await self.dispatcher.evaluate_script(ws_url, script)
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
            metrics = await self.dispatcher.evaluate_script(
                ws_url,
                """({
                    innerWidth: window.innerWidth,
                    innerHeight: window.innerHeight,
                    devicePixelRatio: window.devicePixelRatio || 1,
                    scrollX: window.scrollX || 0,
                    scrollY: window.scrollY || 0
                })""",
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
        حقن مؤشر بصري ينبض (Visual Ripple Effect) مكان النقر على شاشة المستخدم لحظياً من ملف click_ripple.js
        """
        ripple_script = get_script("click_ripple.js", X=x, Y=y)
        try:
            await self.dispatcher.evaluate_script(ws_url, ripple_script)
        except Exception as e:
            logger.debug("show_click_ripple skipped", error=str(e))

    async def get_interactive_elements(self, ws_url: str) -> list[dict[str, Any]]:
        """
        استخراج قائمة العناصر التفاعلية الظاهرة حالياً في الصفحة (أزرار، قوائم، روابط، حقول إدخال)
        مع إحداثياتها الدقيقة في الـ DOM من ملف dom_scanner.js
        """
        scanner_script = get_script("dom_scanner.js")
        try:
            items = await self.dispatcher.evaluate_script(ws_url, scanner_script)
            return items if isinstance(items, list) else []
        except Exception as e:
            logger.warn("Failed to extract interactive elements over CDP", error=str(e))
            return []

    async def wait_for_settle(
        self, ws_url: str, initial_url: str = "", max_wait_sec: float = 2.5
    ) -> float:
        """
        انتظار ذكي لاستقرار الصفحة بعد كل نقرة أو تنقل (DOM-Settle Detection).
        المنطق:
        1. إذا تغير الـ URL -> يعني التنقل تمّ، نبدأ فحص الاستقرار البنيوي.
        2. نقيس عدد العناصر التفاعلية مرتين بفاصل 150ms، إذا تساوى العددان -> الصفحة مستقرة.
        3. حد أقصى صارم (max_wait_sec) لضمان عدم التوقف الأبدي.
        """
        start = time.perf_counter()
        deadline = start + max_wait_sec
        url_changed = False
        prev_element_count = -1

        while time.perf_counter() < deadline:
            await asyncio.sleep(0.12)
            try:
                curr_url = await self.dispatcher.evaluate_script(ws_url, "window.location.href")
                if initial_url and curr_url and curr_url != initial_url:
                    url_changed = True

                is_ready = await self.dispatcher.evaluate_script(
                    ws_url, "document.readyState === 'complete'"
                )
                if not is_ready:
                    continue

                # فحص استقرار عدد عناصر الـ DOM (DOM Element Count Stability)
                count_script = 'document.querySelectorAll(\'button,a,input,select,ng-select,[role="button"],[role="tab"]\').length'
                curr_count = await self.dispatcher.evaluate_script(ws_url, count_script)
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
                for prefix in [
                    "زر",
                    "أيقونة",
                    "قائمة",
                    "خيار",
                    "تبويب",
                    "انقر على",
                    "اضغط على",
                    "الانتقال الى",
                    "اذهب الى",
                ]:
                    if clean_target.startswith(prefix):
                        clean_target = clean_target[len(prefix) :].strip()

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
                    logger.info(
                        "DOM-Anchor snapped click by semantic text match",
                        target=clean_target,
                        matched_text=best_el.get("text"),
                        x=target_x,
                        y=target_y,
                    )

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
                    logger.info(
                        "DOM-Anchor snapped click by proximity",
                        dist=best_dist,
                        element=best_el.get("text"),
                        x=target_x,
                        y=target_y,
                    )

        # تنفيذ النقر الفعلي عند الإحداثيات المنجذبة
        await self.dispatcher.click_at(ws_url, target_x, target_y)
        return target_x, target_y, snapped

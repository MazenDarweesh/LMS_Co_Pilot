"""
Multimodal Vision Grounding Service for DynamicPro ERP.
Uses Gemini Vision to inspect ERP screenshots, understand UI state, and predict exact pixel coordinates [x, y]
for hardware-level mouse clicks, text inputs, and keyboard navigation.
"""

import asyncio
import base64
import json
from typing import Any, Optional
import structlog
from google import genai
from google.genai import types

from src.core.config import settings
from src.core.prompts import (
    VISION_DOM_FIRST_PROMPT_TEMPLATE,
    VISION_GROUNDING_SYSTEM_PROMPT,
    get_vision_dom_first_prompt,
    get_vision_grounding_prompt,
)

logger = structlog.get_logger()

__all__ = [
    "VISION_DOM_FIRST_PROMPT_TEMPLATE",
    "VISION_GROUNDING_SYSTEM_PROMPT",
    "VisionGroundingService",
    "get_vision_dom_first_prompt",
    "get_vision_grounding_prompt",
    "vision_grounding_service",
]


class VisionGroundingService:
    """
    خدمة التحليل البصري واستخراج الإحداثيات بواسطة Gemini Multimodal.
    """

    def __init__(self) -> None:
        self._client: Optional[genai.Client] = None

    def initialize(self) -> None:
        try:
            self._client = genai.Client(api_key=settings.GEMINI_API_KEY)
            logger.info("Vision Grounding Service initialized successfully")
        except Exception as e:
            logger.error("Failed to initialize Gemini Client in VisionGroundingService", error=str(e))
            self._client = None

    async def predict_next_action(
        self,
        screenshot_b64: str,
        goal: str,
        history: list[dict[str, Any]],
        viewport_metrics: Optional[dict[str, float]] = None,
        timeout: float = 14.0,
    ) -> dict[str, Any]:
        """
        تحليل لقطة الشاشة واستخراج الخطوة التالية بدقة.
        """
        if not self._client:
            self.initialize()

        if not self._client:
            return {
                "thought": "فشل تهيئة عميل الذكاء الاصطناعي البصري",
                "action": "done",
                "is_terminal": True,
            }

        vp = viewport_metrics or {"width": 1280.0, "height": 720.0, "dpr": 1.0}
        image_bytes = base64.b64decode(screenshot_b64)
        history_json = json.dumps(history[-6:], ensure_ascii=False, indent=2) if history else "[]"
        prompt = get_vision_grounding_prompt(
            goal=goal,
            viewport_width=int(vp.get("width", 1280)),
            viewport_height=int(vp.get("height", 720)),
            dpr=float(vp.get("dpr", 1.0)),
            history_json=history_json,
        )

        try:
            resp = await asyncio.wait_for(
                asyncio.to_thread(
                    self._client.models.generate_content,
                    model=settings.GEMINI_MODEL,
                    contents=[
                        types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
                        prompt,
                    ],
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        temperature=0.0,
                    ),
                ),
                timeout=timeout,
            )

            raw_text = resp.text if hasattr(resp, "text") and resp.text else "{}"
            result: dict[str, Any] = json.loads(raw_text)
            logger.info(
                "Vision Grounding predicted action",
                action=result.get("action"),
                thought=result.get("thought"),
                coord=result.get("coordinate"),
            )
            return result
        except Exception as e:
            logger.error("Vision Grounding inference failed", error=str(e))
            return {
                "thought": f"خطأ أثناء التحليل البصري: {str(e)}",
                "action": "wait",
                "is_terminal": False,
            }

    async def predict_from_elements(
        self,
        goal: str,
        elements: list[dict[str, Any]],
        page_state: dict[str, Any],
        history: list[dict[str, Any]],
        timeout: float = 8.0,
    ) -> dict[str, Any]:
        """
        الوضع النصي السريع (DOM-First): اختيار العنصر التفاعلي من قائمة نصية مرقمة
        دون الحاجة لنقل أو معالجة صور لتقليل زمن الاستجابة (Latency) وتفادي أخطاء الإحداثيات.
        """
        if not self._client:
            self.initialize()

        if not self._client:
            return {"thought": "فشل تهيئة عميل الذكاء الاصطناعي", "action": "wait"}

        # تحضير قائمة العناصر المرقمة
        elements_text = []
        for idx, el in enumerate(elements[:60]):
            txt = (el.get("text") or "").strip()
            tag = el.get("tag", "btn")
            if txt:
                elements_text.append(f"[{idx}] {tag}: \"{txt}\"")

        dom_prompt = get_vision_dom_first_prompt(
            goal=goal,
            page_url=page_state.get("url", ""),
            page_title=page_state.get("title", ""),
            headings_json=json.dumps(page_state.get("headings", []), ensure_ascii=False),
            history_json=json.dumps(history[-4:], ensure_ascii=False, indent=1) if history else "[]",
            elements_text="\n".join(elements_text) if elements_text else "No elements found",
        )
        try:
            resp = await asyncio.wait_for(
                asyncio.to_thread(
                    self._client.models.generate_content,
                    model=settings.GEMINI_MODEL,
                    contents=dom_prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        temperature=0.0,
                    ),
                ),
                timeout=timeout,
            )
            raw_text = resp.text if hasattr(resp, "text") and resp.text else "{}"
            result: dict[str, Any] = json.loads(raw_text)
            logger.info(
                "DOM-First predicted action",
                action=result.get("action"),
                element_id=result.get("element_id"),
                thought=result.get("thought"),
            )
            return result
        except Exception as e:
            logger.warn("DOM-First text inference failed, falling back", error=str(e))
            return {"action": "fallback", "element_id": None, "thought": str(e)}


# Singleton instance
vision_grounding_service = VisionGroundingService()

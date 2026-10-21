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

logger = structlog.get_logger()

VISION_GROUNDING_SYSTEM_PROMPT = """You are an autonomous ERP Visual Operator for DynamicPro ERP (an Arabic enterprise accounting & warehouse web system).
You inspect a high-resolution screenshot of the user's active browser window, observe the open screens, dialogs, dropdowns, and data tables, and determine the single next physical action (mouse click or keyboard typing) required to make progress toward the user's goal.

TARGET GOAL:
"{goal}"

ACTIVE BROWSER VIEWPORT:
Width: {viewport_width}px, Height: {viewport_height}px, DevicePixelRatio: {dpr}

ACTION HISTORY SO FAR:
{history_json}

RULES & UI CHARACTERISTICS IN DYNAMICPRO ERP:
1. Arabic RTL Layout:
   - Primary action buttons (like "اضافة جديد" / "حفظ" / "بحث") are located on the TOP-RIGHT or within dedicated toolbars.
   - Form field labels appear to the RIGHT of (or directly above) their input or dropdown boxes. Always target the input field box itself, NOT the text label!
   - For dropdowns (<ng-select> / <eg-select>), click inside the dropdown container box or the small downward arrow on the left to reveal options.
2. In-Grid Editing:
   - To add a row to an invoice or transaction grid, look for a button labeled "اضافة جديد" or "اضافة صفوف" located directly below or within the grid section.
   - To edit a cell in a row, click directly inside the target column cell.
3. Terminal Condition:
   - When all required header fields are populated and all line items are inserted, or when reaching the confirmation step, select action "done".
   - NEVER click "اعتماد" (Approve) or "حفظ نهائي" (Final Post) automatically. The agent stops at "done" once the draft is ready for user review.

COORDINATE SPECIFICATION:
- Return physical pixel coordinates [x, y] strictly within [0..{viewport_width}] for x and [0..{viewport_height}] for y.
- Target the visual CENTER of the clickable button, input field, or menu item.
- Do NOT click on static labels or empty background margins.
- Provide the exact visible text of the button/menu item in "target_text" whenever clicking a labeled element.

OUTPUT FORMAT:
Return ONLY a valid JSON object matching this schema:
{{
  "thought": "شرح موجز بالعربية لما تراه في الشاشة والخطوة التالية التي ستقوم بها",
  "action": "click" | "type" | "press_key" | "wait" | "done",
  "coordinate": [x, y],
  "target_text": "اسم أو نص الزر أو العنصر المراد النقر عليه بالعربية (مثل: الموردين والمشتريات، فواتير المشتريات، اضافة جديد)، أو null",
  "text": "text to type if action is type, else null",
  "key": "Enter|Tab|Escape if action is press_key, else null",
  "is_terminal": true or false
}}
"""


class VisionGroundingService:
    """
    خدمة التحليل البصري واستخراج الإحداثيات بواسطة Gemini Multimodal.
    """

    def __init__(self) -> None:
        self._client: Optional[genai.Client] = None

    def initialize(self) -> None:
        try:
            self._client = genai.Client(api_key=settings.GEMINI_API_KEY)
            logger.info("Vision Grounding Service initialized successfully ✅")
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
        prompt = VISION_GROUNDING_SYSTEM_PROMPT.format(
            goal=goal,
            viewport_width=int(vp.get("width", 1280)),
            viewport_height=int(vp.get("height", 720)),
            dpr=vp.get("dpr", 1.0),
            history_json=json.dumps(history[-6:], ensure_ascii=False, indent=2) if history else "[]",
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


# Singleton instance
vision_grounding_service = VisionGroundingService()

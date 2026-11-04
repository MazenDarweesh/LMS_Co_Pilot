"""
CDP Polymorphic Form Filling & Auto-Cataloging Engine.
Injects document headers, handles Angular @ng-select dropdowns, inserts line items,
resolves automated totals, captures form states, and auto-catalogs screens into forms_catalog_service.
"""

import json
from typing import Any, Optional
import structlog

from src.services.agentic_stepper.session_telemetry import (
    TelemetryStage,
    append_session_event,
)
from src.services.cdp.input_dispatcher import CdpInputDispatcher
from src.services.cdp.script_loader import get_script

logger = structlog.get_logger()


class CdpFormBridge:
    """
    محرك التعبئة متعدد الأشكال والاستكشاف الذاتي لنماذج الـ ERP.
    يتعامل مع الـ DOM مباشرة، ويملأ الحقول وقوائم ng-select، ويسجل الشاشات ذاتياً في الكتالوج.
    """

    def __init__(self, dispatcher: CdpInputDispatcher) -> None:
        self.dispatcher = dispatcher

    async def fill_erp_form_bridge(
        self, ws_url: str, payload: dict[str, Any], session_id: Optional[str] = None
    ) -> dict[str, Any]:
        """
        حقن وتعبئة الفاتورة وجدول الأصناف مباشرة عبر جسر window.DynamicERP.fillFormData(payload)
        أو عبر استدعاء محرك التعبئة المباشر فائق الدقة المحمل من form_injector.js.
        """
        payload_json = json.dumps(payload, ensure_ascii=False)
        script = get_script("form_injector.js", PAYLOAD=payload_json)
        try:
            res = await self.dispatcher.evaluate_script(ws_url, script, timeout=25.0)
            result = res if isinstance(res, dict) else {"success": bool(res), "method": "bridge_raw"}
            if not result.get("success") and session_id:
                append_session_event(
                    session_id,
                    "WARN",
                    TelemetryStage.CDP_FORM_BRIDGE,
                    "Form fill bridge returned failure status",
                    result,
                )
            return result
        except Exception as e:
            logger.error("Failed to execute bridge/precision form fill", error=str(e))
            if session_id:
                append_session_event(
                    session_id,
                    "ERROR",
                    TelemetryStage.CDP_FORM_BRIDGE,
                    f"Form bridge execution exception: {str(e)}",
                    {"error": str(e)},
                )
            return {"success": False, "error": str(e)}

    async def snapshot_form_state(self, ws_url: str) -> dict[str, Any]:
        """
        لقطة اكتشاف ذاتي من الـ ERP نفسه من ملف form_snapshot.js.
        """
        script = get_script("form_snapshot.js")
        try:
            res = await self.dispatcher.evaluate_script(ws_url, script, timeout=10.0)
            return res if isinstance(res, dict) else {}
        except Exception as e:
            logger.error("snapshot_form_state failed", error=str(e))
            return {"error": str(e)}

    async def get_active_screen_metadata(self, ws_url: str) -> list[dict[str, Any]]:
        """
        استخراج ميتاداتا الشاشة النشطة لحظياً (0ms) مباشرة من ذاكرة Angular (RxJS columnList BehaviorSubject)
        من ملف screen_metadata.js.
        """
        script = get_script("screen_metadata.js")
        try:
            res = await self.dispatcher.evaluate_script(ws_url, script, timeout=8.0)
            return res if isinstance(res, list) else []
        except Exception as e:
            logger.debug("get_active_screen_metadata failed", error=str(e))
            return []

    async def inspect_active_page_dom(self, ws_url: str) -> dict[str, Any]:
        """
        فحص الـ DOM المباشر للشاشة المفتوحة حالياً في المتصفح لاستخراج جميع عناصر Angular
        والـ formControls والتسميات العربية والجداول تلقائياً من ملف page_inspection.js.
        """
        script = get_script("page_inspection.js")
        try:
            res = await self.dispatcher.evaluate_script(ws_url, script, timeout=12.0)
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

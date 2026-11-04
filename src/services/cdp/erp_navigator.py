"""
CDP ERP Host Navigation & Screen Detection Service.
Interacts with the Angular ERP host runtime (window.DynamicERP, app-base pageService)
to navigate screens and open input forms.
"""

import json
from typing import Any
import structlog

from src.services.cdp.input_dispatcher import CdpInputDispatcher
from src.services.cdp.script_loader import get_script

logger = structlog.get_logger()


class CdpErpNavigator:
    """
    مسؤول عن الملاحة الذكية والتنقل بين شاشات الـ ERP (عبر الجسر البرمجي أو الـ DOM)،
    واستخراج صلاحيات شاشات المستخدم، وضمان فتح نموذج الإدخال الرئيسي.
    """

    def __init__(self, dispatcher: CdpInputDispatcher) -> None:
        self.dispatcher = dispatcher

    async def navigate_to_erp_screen(self, ws_url: str, screen_id_or_name: Any) -> bool:
        """
        استدعاء مباشر لجسر ERP الداخلي للانتقال للشاشة المطلوبة في خطوة واحدة
        من ملف erp_navigation.js.
        """
        script = get_script("erp_navigation.js", TARGET=json.dumps(screen_id_or_name))
        try:
            return bool(await self.dispatcher.evaluate_script(ws_url, script))
        except Exception as e:
            logger.warning("CDP Bridge navigateToScreen failed", error=str(e))
            return False

    async def navigate_to_erp_screen_dom_click(self, ws_url: str, screen_id_or_name: Any) -> bool:
        """
        Fallback DOM-click navigation: بحث عن عنصر [data-page-id] أو [routerlink] أو القائمة الجانبية
        والنقر عليه مباشرة من ملف dom_navigation.js.
        """
        script = get_script("dom_navigation.js", TARGET=json.dumps(screen_id_or_name))
        try:
            res = await self.dispatcher.evaluate_script(ws_url, script)
            logger.info("DOM click navigation executed", target=screen_id_or_name, success=bool(res))
            return bool(res)
        except Exception as e:
            logger.warning("DOM click navigation failed", error=str(e), target=screen_id_or_name)
            return False

    async def get_user_authorized_screens(self, ws_url: str) -> list[dict[str, Any]]:
        """
        استدعاء مباشر لجسر window.DynamicERP.listUserPages() لجلب الشاشات المسموحة للمستخدم الحالي
        مباشرة من ذاكرة المتصفح من ملف user_authorized_screens.js.
        """
        script = get_script("user_authorized_screens.js")
        try:
            res = await self.dispatcher.evaluate_script(ws_url, script, timeout=8.0)
            return res if isinstance(res, list) else []
        except Exception as e:
            logger.warning("CDP Bridge get_user_authorized_screens failed", error=str(e))
            return []

    async def ensure_erp_form_open(self, ws_url: str, timeout_sec: float = 8.0) -> dict[str, Any]:
        """
        يضمن أن فورم الإدخال (AddOrEdit) مفتوح من ملف ensure_form_open.js.
        """
        script = get_script("ensure_form_open.js", TIMEOUT_MS=int(timeout_sec * 1000))
        try:
            res = await self.dispatcher.evaluate_script(ws_url, script, timeout=timeout_sec + 6.0)
            return res if isinstance(res, dict) else {"opened": bool(res), "method": "raw"}
        except Exception as e:
            logger.error("ensure_erp_form_open failed", error=str(e))
            return {"opened": False, "method": "error", "error": str(e)}

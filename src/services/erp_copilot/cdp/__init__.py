"""
CDP (Chrome DevTools Protocol) Agent Package.
Exposes modular CDP components alongside the unified CdpAgentService Facade
for 100% backward-compatibility with zero breaking changes.
"""

from typing import Any
import httpx
from pydoll.connection.connection_handler import ConnectionHandler
import structlog

from src.services.cdp.connection_manager import CdpConnectionManager
from src.services.cdp.input_dispatcher import CdpInputDispatcher
from src.services.cdp.visual_grounding import CdpVisualGrounding
from src.services.cdp.erp_navigator import CdpErpNavigator
from src.services.cdp.form_bridge import CdpFormBridge

logger = structlog.get_logger()


class CdpAgentService:
    """
    الواجهة الموحدة (Facade) للتحكم في المتصفح عبر بروتوكول CDP.
    تجمع بين إدارة الاتصالات، إرسال نبضات العتاد، الرصد البصري، الملاحة، وحقن النماذج.
    توفر توافقية كاملة (Zero Breaking Changes) مع الحفاظ على عزل المسؤوليات وتفكيك الكود.
    """

    def __init__(self, default_port: int = 9222) -> None:
        self.default_port = default_port
        self.connection = CdpConnectionManager(default_port=default_port)
        self.dispatcher = CdpInputDispatcher(self.connection)
        self.visual = CdpVisualGrounding(self.dispatcher)
        self.dispatcher.set_ripple_callback(self.visual.show_click_ripple)
        self.navigator = CdpErpNavigator(self.dispatcher)
        self.form = CdpFormBridge(self.dispatcher)

    # ─── 1. Connection & Lifecycle Delegation ────────────────────────────

    async def _get_http_client(self) -> httpx.AsyncClient:
        return await self.connection.get_http_client()

    async def _get_pydoll_handler(self, ws_url: str) -> ConnectionHandler:
        return await self.connection.get_pydoll_handler(ws_url)

    async def aclose(self) -> None:
        await self.connection.aclose()

    def _resolve_urls(self, host: str, port: int) -> tuple[str, str]:
        return self.connection.resolve_urls(host, port)

    async def is_cdp_available(self, port: int | None = None, host: str = "127.0.0.1") -> bool:
        return await self.connection.is_cdp_available(port=port, host=host)

    async def ensure_cdp_available(
        self, port: int | None = None, host: str = "127.0.0.1", session_id: Any = None
    ) -> bool:
        return await self.connection.ensure_cdp_available(port=port, host=host, session_id=session_id)

    async def get_active_erp_tab(
        self, port: int | None = None, host: str = "127.0.0.1", title_match: str = "", session_id: Any = None
    ) -> dict[str, Any] | None:
        return await self.connection.get_active_erp_tab(port=port, host=host, title_match=title_match, session_id=session_id)

    # ─── 2. Low-Level Protocol & Hardware Input Delegation ───────────────

    async def execute_cdp_command(
        self, ws_url: str, method: str, params: dict[str, Any] | None = None, timeout: float = 6.0
    ) -> dict[str, Any]:
        return await self.dispatcher.execute_cdp_command(ws_url, method, params=params, timeout=timeout)

    async def evaluate_script(self, ws_url: str, script: str, timeout: float = 15.0) -> Any:
        return await self.dispatcher.evaluate_script(ws_url, script, timeout=timeout)

    async def click_at(self, ws_url: str, x: int, y: int) -> None:
        await self.dispatcher.click_at(ws_url, x, y)

    async def type_text(self, ws_url: str, text: str, delay_ms: float = 30) -> None:
        await self.dispatcher.type_text(ws_url, text, delay_ms=delay_ms)

    async def press_key(self, ws_url: str, key_name: str) -> None:
        await self.dispatcher.press_key(ws_url, key_name)

    # ─── 3. Visual Grounding & DOM Inspection Delegation ────────────────

    @staticmethod
    def normalize_ar(s: str) -> str:
        return CdpVisualGrounding.normalize_ar(s)

    async def capture_screenshot(
        self, ws_url: str, quality: int = 80, mask_chat: bool = True
    ) -> str:
        return await self.visual.capture_screenshot(ws_url, quality=quality, mask_chat=mask_chat)

    async def get_page_state(self, ws_url: str) -> dict[str, Any]:
        return await self.visual.get_page_state(ws_url)

    async def get_viewport_metrics(self, ws_url: str) -> dict[str, float]:
        return await self.visual.get_viewport_metrics(ws_url)

    async def show_click_ripple(self, ws_url: str, x: int, y: int) -> None:
        await self.visual.show_click_ripple(ws_url, x, y)

    async def get_interactive_elements(self, ws_url: str) -> list[dict[str, Any]]:
        return await self.visual.get_interactive_elements(ws_url)

    async def wait_for_settle(
        self, ws_url: str, initial_url: str = "", max_wait_sec: float = 2.5
    ) -> float:
        return await self.visual.wait_for_settle(ws_url, initial_url=initial_url, max_wait_sec=max_wait_sec)

    async def click_element_or_coordinate(
        self,
        ws_url: str,
        x: int,
        y: int,
        target_text: str | None = None,
        interactive_elements: list[dict[str, Any]] | None = None,
    ) -> tuple[int, int, bool]:
        return await self.visual.click_element_or_coordinate(
            ws_url, x, y, target_text=target_text, interactive_elements=interactive_elements
        )

    # ─── 4. ERP Host Navigation Delegation ───────────────────────────────

    async def navigate_to_erp_screen(
        self, ws_url: str, screen_id_or_name: Any, session_id: Any = None
    ) -> bool:
        return await self.navigator.navigate_to_erp_screen(ws_url, screen_id_or_name, session_id=session_id)

    async def navigate_to_erp_screen_dom_click(
        self, ws_url: str, screen_id_or_name: Any, session_id: Any = None
    ) -> bool:
        return await self.navigator.navigate_to_erp_screen_dom_click(ws_url, screen_id_or_name, session_id=session_id)

    async def get_user_authorized_screens(self, ws_url: str) -> list[dict[str, Any]]:
        return await self.navigator.get_user_authorized_screens(ws_url)

    async def ensure_erp_form_open(
        self, ws_url: str, timeout_sec: float = 8.0, session_id: Any = None
    ) -> dict[str, Any]:
        return await self.navigator.ensure_erp_form_open(ws_url, timeout_sec=timeout_sec, session_id=session_id)

    # ─── 5. Form Bridge & Auto-Cataloging Delegation ─────────────────────

    async def fill_erp_form_bridge(
        self, ws_url: str, payload: dict[str, Any], session_id: Any = None
    ) -> dict[str, Any]:
        return await self.form.fill_erp_form_bridge(ws_url, payload, session_id=session_id)

    async def snapshot_form_state(self, ws_url: str) -> dict[str, Any]:
        return await self.form.snapshot_form_state(ws_url)

    async def get_active_screen_metadata(self, ws_url: str) -> list[dict[str, Any]]:
        return await self.form.get_active_screen_metadata(ws_url)

    async def inspect_active_page_dom(self, ws_url: str) -> dict[str, Any]:
        return await self.form.inspect_active_page_dom(ws_url)

    async def auto_catalog_active_page(self, ws_url: str, persist: bool = False) -> dict[str, Any]:
        return await self.form.auto_catalog_active_page(ws_url, persist=persist)


# Default Singleton Instance
cdp_agent_service = CdpAgentService()

__all__ = [
    "CdpAgentService",
    "cdp_agent_service",
    "CdpConnectionManager",
    "CdpInputDispatcher",
    "CdpVisualGrounding",
    "CdpErpNavigator",
    "CdpFormBridge",
]

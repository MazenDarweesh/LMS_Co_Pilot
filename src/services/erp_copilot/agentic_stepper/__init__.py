"""
Autonomous Agentic Stepper Modular Package & Composite Facade.
Provides backward-compatible AgenticStepperService aggregating:
- SessionTelemetry: Black-box logging and unified audit ledger
- ScreenResolver: Arabic tokenization, intent scoring, and screen matching
- PayloadExtractor: Dynamic transaction JSON extraction from natural language
- StepperEngine: Streaming goal execution loop (SSE Generator)
"""

from typing import Any, AsyncGenerator, Optional

from src.services.erp_copilot.agentic_stepper.payload_extractor import PayloadExtractor
from src.services.erp_copilot.agentic_stepper.screen_resolver import ScreenResolver
from src.services.erp_copilot.agentic_stepper.session_telemetry import (
    ERP_LOGS_DIR,
    SHARED_LOGS_DIR,
    TelemetryStage,
    _append_session_event,
    append_session_event,
    read_session_events,
)
from src.services.erp_copilot.agentic_stepper.stepper_engine import StepperEngine


class AgenticStepperService:
    """
    الواجهة الموحدة المعمارية (Composite Facade) لمحرك الأتمتة البصرية المستقل.
    تجمع الوحدات الفرعية المتخصصة وتوفر توافقية بنسبة 100% مع كافة الاستدعاءات السابقة.
    """

    def __init__(self, default_max_steps: int = 15) -> None:
        self.default_max_steps = default_max_steps
        self.resolver = ScreenResolver()
        self.extractor = PayloadExtractor()
        self.engine = StepperEngine(
            resolver=self.resolver,
            extractor=self.extractor,
            default_max_steps=self.default_max_steps,
        )

    # -------------------------------------------------------------------------
    # Backward-Compatible Properties (الخصائص التوافقية للمكتبات والاختبارات)
    # -------------------------------------------------------------------------
    @property
    def _catalog(self) -> Optional[list[dict[str, Any]]]:
        return self.resolver._catalog

    @_catalog.setter
    def _catalog(self, val: Optional[list[dict[str, Any]]]) -> None:
        self.resolver._catalog = val

    @property
    def _session_screens_cache(self) -> dict[str, list[dict[str, Any]]]:
        return self.resolver._session_screens_cache

    # -------------------------------------------------------------------------
    # Delegated Public API (تفويض الاستدعاءات للوحدات المتخصصة)
    # -------------------------------------------------------------------------
    def _load_screens_catalog(self) -> list[dict[str, Any]]:
        """تحميل كتالوج الشاشات في الذاكرة (مفوض لـ ScreenResolver)"""
        return self.resolver._load_screens_catalog()

    async def get_cached_user_screens(
        self, ws_url: str, session_id: Optional[str] = None
    ) -> list[dict[str, Any]]:
        """جلب شاشات المستخدم المصرح بها وتخزينها في ذاكرة الجلسة"""
        return await self.resolver.get_cached_user_screens(ws_url, session_id=session_id)

    async def resolve_target_screen(
        self, goal: str, authorized_screens: list[dict[str, Any]]
    ) -> Optional[dict[str, Any]]:
        """المطابقة الدلالية الذكية بين الهدف والشاشات المتاحة"""
        return await self.resolver.resolve_target_screen(goal, authorized_screens)

    async def extract_transaction_payload(
        self,
        goal: str,
        target_screen: Optional[dict[str, Any]] = None,
        target_page_id: Optional[int] = None,
        timeout: float = 15.0,
    ) -> dict[str, Any]:
        """استخراج بيانات المعاملة المنظمة بالذكاء الاصطناعي بناءً على مواصفات النموذج"""
        return await self.extractor.extract_transaction_payload(
            goal=goal,
            target_screen=target_screen,
            target_page_id=target_page_id,
            timeout=timeout,
        )

    async def execute_goal_stream(
        self,
        goal: str,
        cdp_port: int = 9222,
        cdp_host: str = "127.0.0.1",
        session_id: Optional[str] = None,
        max_steps: Optional[int] = None,
        title_match: str = "dynamic",
    ) -> AsyncGenerator[dict[str, Any], None]:
        """تشغيل حلقة الأتمتة وبث التقدم للمستخدم لحظة بلحظة"""
        async for event in self.engine.execute_goal_stream(
            goal=goal,
            cdp_port=cdp_port,
            cdp_host=cdp_host,
            session_id=session_id,
            max_steps=max_steps,
            title_match=title_match,
        ):
            yield event


    def read_session_events(
        self,
        session_id: str,
        stage_prefix: Optional[str | TelemetryStage] = None,
        level: Optional[str] = None,
        limit: int = 300,
    ) -> list[dict[str, Any]]:
        """قراءة وفلترة أحداث الصندوق الأسود للجلسة المحددة"""
        return read_session_events(session_id, stage_prefix=stage_prefix, level=level, limit=limit)


# Singleton default instance
agentic_stepper_service = AgenticStepperService()

__all__ = [
    "AgenticStepperService",
    "agentic_stepper_service",
    "ScreenResolver",
    "PayloadExtractor",
    "StepperEngine",
    "TelemetryStage",
    "append_session_event",
    "_append_session_event",
    "read_session_events",
    "ERP_LOGS_DIR",
    "SHARED_LOGS_DIR",
]


"""
CDP Connection & Lifecycle Manager.
Handles Chrome browser process spawning, HTTP and WebSocket connection pooling via pydoll,
DevTunnel URL resolution, and tab discovery.
"""

import asyncio
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any, Optional
import httpx
from pydoll.connection.connection_handler import ConnectionHandler
import structlog

from src.core.config import settings
from src.services.agentic_stepper.session_telemetry import (
    TelemetryStage,
    append_session_event,
)

logger = structlog.get_logger()



class CdpConnectionManager:
    """
    إدارة دورة حياة الاتصال بمتصفح Chrome عبر بروتوكول CDP.
    تتولى إدارة عميل HTTP المشترك، قنوات WebSocket لـ pydoll، واكتشاف التبويبات النشطة.
    """

    def __init__(self, default_port: int = 9222) -> None:
        self.default_port = default_port
        self._chrome_proc: subprocess.Popen | None = None
        self._http_client: httpx.AsyncClient | None = None
        self._pydoll_handlers: dict[str, ConnectionHandler] = {}
        self._handler_lock = asyncio.Lock()

    async def get_http_client(self) -> httpx.AsyncClient:
        """إرجاع عميل HTTP مشترك مدار لتجنب إنشاء اتصالات متكررة واستنزاف المقابس"""
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(timeout=4.0, verify=False)
        return self._http_client

    async def get_pydoll_handler(self, ws_url: str) -> ConnectionHandler:
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

    async def drop_handler(self, ws_url: str) -> None:
        """إغلاق وحذف كائن ConnectionHandler الخاص برابط معين لإعادة بنائه"""
        async with self._handler_lock:
            old_h = self._pydoll_handlers.pop(ws_url, None)
            if old_h:
                try:
                    await old_h.close()
                except Exception:
                    pass

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

    def resolve_urls(self, host: str, port: int) -> tuple[str, str]:
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
        base_http, _ = self.resolve_urls(h, p)
        client = await self.get_http_client()

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

    async def ensure_cdp_available(
        self, port: int | None = None, host: str = "127.0.0.1", session_id: Optional[str] = None
    ) -> bool:
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
            if session_id:
                append_session_event(
                    session_id,
                    "INFO",
                    TelemetryStage.CDP_CONNECT,
                    f"Local Chrome CDP offline; auto-spawning Chrome instance on port {p}...",
                    {"port": p, "host": h},
                )
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
                            if session_id:
                                append_session_event(
                                    session_id,
                                    "INFO",
                                    TelemetryStage.CDP_CONNECT,
                                    f"Auto-spawned Chrome CDP is online and reachable on port {p}",
                                    {"port": p, "pid": self._chrome_proc.pid},
                                )
                            return True
            except Exception as e:
                logger.error("Failed to auto-launch Chrome with CDP", error=str(e))
                if session_id:
                    append_session_event(
                        session_id,
                        "ERROR",
                        TelemetryStage.CDP_CONNECT,
                        f"Failed to auto-launch Chrome with CDP: {str(e)}",
                        {"error": str(e), "port": p},
                    )
        else:
            if session_id:
                append_session_event(
                    session_id,
                    "WARN",
                    TelemetryStage.CDP_CONNECT,
                    f"Remote CDP endpoint unreachable: {h}:{p}",
                    {"host": h, "port": p},
                )

        return False

    async def get_active_erp_tab(
        self,
        port: int | None = None,
        host: str = "127.0.0.1",
        title_match: str = "",
        session_id: Optional[str] = None,
    ) -> dict[str, Any] | None:
        """
        البحث عن التبويب النشط لنظام DynamicPro ERP واستخراج عنوان الـ WebSocket للتصحيح مع إعادة المحاولة.
        """
        p = port or self.default_port
        h = host or "127.0.0.1"
        base_http, base_ws = self.resolve_urls(h, p)
        client = await self.get_http_client()

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
                if session_id:
                    append_session_event(
                        session_id,
                        "INFO",
                        TelemetryStage.CDP_CONNECT,
                        f"Attached to active ERP tab: '{target_tab.get('title')}'",
                        {"ws_url": target_tab.get("clean_ws_url"), "url": target_tab.get("url")},
                    )
                return target_tab
            except Exception as e:
                logger.debug("get_active_erp_tab attempt failed", attempt=attempt, error=str(e))
                if attempt == 0:
                    await asyncio.sleep(0.35)

        if session_id:
            append_session_event(
                session_id,
                "WARN",
                TelemetryStage.CDP_CONNECT,
                f"No active ERP tab found on {base_http}/json after retries",
                {"host": h, "port": p, "title_match": title_match},
            )
        return None

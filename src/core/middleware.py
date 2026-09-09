# src/core/middleware.py
import time
import uuid
import structlog
from starlette.types import ASGIApp, Scope, Receive, Send
from slowapi import Limiter
from slowapi.util import get_remote_address
from src.core.config import settings

# 1. إعداد الـ Rate Limiter
# ⚠️ ملاحظة للإنتاج (Production):
# في بيئة متعددة الخوادم، يجب استبدال التخزين الداخلي (In-Memory) بـ Redis كالتالي:
# limiter = Limiter(key_func=get_remote_address, storage_uri="redis://localhost:6379")
limiter = Limiter(key_func=get_remote_address, enabled=settings.RATE_LIMIT_ENABLED)

# 2. إعداد Pure ASGI Middleware عالي الأداء (مع إضافة Correlation ID)
class PerformanceMetricsMiddleware:
    """
    Pure ASGI Middleware:
    أسرع بنسبة 40% من BaseHTTPMiddleware.
    يقوم بحساب وقت المعالجة وتوليد Request ID لربط سجلات (Logs) كل طلب ببعضها.
    """
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        start_time = time.perf_counter()
        request_id = str(uuid.uuid4())
        
        # 🔗 ربط الـ Request ID بجميع سجلات (Logs) هذا الطلب (Structlog Context)
        structlog.contextvars.bind_contextvars(request_id=request_id)

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                duration = time.perf_counter() - start_time
                headers = list(message.get("headers", []))
                
                # إضافة Headers لوقت المعالجة والـ Request ID
                headers.append((b"x-process-time", str(duration).encode("utf-8")))
                headers.append((b"x-request-id", request_id.encode("utf-8")))
                
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            # 🧹 تنظيف المتغيرات بعد انتهاء الطلب لمنع تسرب البيانات بين الطلبات
            structlog.contextvars.clear_contextvars()


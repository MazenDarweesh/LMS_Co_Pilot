import sys
import asyncio
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from slowapi.errors import RateLimitExceeded

from src.core.config import settings
from src.core.logging import setup_logging
from src.api.v1.router import router as api_router
from src.db.session import lifespan
from src.core.middleware import limiter, PerformanceMetricsMiddleware

# 1. تهيئة الـ Logging الموحد للنظام
setup_logging()

# 2. إنشاء تطبيق FastAPI
app = FastAPI(
    title=settings.PROJECT_NAME,
    description="LMS AI Co-Pilot API Engine",
    version="1.0.0",
    lifespan=lifespan
)

# 3. إعداد الـ Rate Limiter ومعالجة تجاوز الحد
app.state.limiter = limiter

@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    """
    إرجاع رسالة JSON احترافية بدلاً من صفحة خطأ غير مهندمة عندما يتجاوز المستخدم حد الطلبات.
    """
    return JSONResponse(
        status_code=429,
        content={"detail": f"Rate limit exceeded. Please try again later. ({exc.detail})"}
    )

# 4. تفعيل الـ Middlewares
# ملاحظة: FastAPI يقوم بتنفيذ الميدل وير من الأسفل للأعلى (الذي يُضاف آخراً يُنفذ أولاً للطلب القادم).

# أ. ميدل وير الأداء والـ Request ID
app.add_middleware(PerformanceMetricsMiddleware)

# ب. ميدل وير حماية الـ Host
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=["localhost", "127.0.0.1", "*.egydynamic.com"]
)

# ج. ميدل وير الـ CORS (يجب أن يكون خارجياً ليتعامل مع طلبات الـ Preflight)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 5. تسجيل مسارات الـ API
app.include_router(api_router)

from src.api.v1.speech import router as speech_router
app.include_router(speech_router)

@app.get("/health", tags=["System"])
async def health_check():
    return {"status": "ok", "environment": settings.ENVIRONMENT}

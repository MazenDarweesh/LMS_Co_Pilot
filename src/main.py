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
from src.api.v1.router import router as api_router, api_compat_router
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

from fastapi.exceptions import RequestValidationError

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

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    import structlog
    structlog.get_logger().error(
        "Request validation failed ❌",
        path=request.url.path,
        errors=exc.errors(),
        body=exc.body,
    )
    return JSONResponse(
        status_code=422,
        content={"detail": exc.errors()},
    )

# 4. تفعيل الـ Middlewares
# ملاحظة: FastAPI يقوم بتنفيذ الميدل وير من الأسفل للأعلى (الذي يُضاف آخراً يُنفذ أولاً للطلب القادم).

# أ. ميدل وير الأداء والـ Request ID
app.add_middleware(PerformanceMetricsMiddleware)

# ب. ميدل وير حماية الـ Host
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=settings.ALLOWED_HOSTS
)

# ج. ميدل وير الـ CORS مع دعم نمط Wildcard لأنفاق DevTunnel و ngrok السحابية
# CORSMiddleware الرسمي لا يدعم wildcards مثل *.devtunnels.ms، لذا نبني قائمة ديناميكية
import re as _re

_TUNNEL_PATTERNS = [
    _re.compile(r"https://[a-z0-9\-]+\.devtunnels\.ms"),
    _re.compile(r"https://[a-z0-9\-]+\.ngrok\.io"),
    _re.compile(r"https://[a-z0-9\-]+\.ngrok-free\.app"),
]

def _is_allowed_origin(origin: str) -> bool:
    """فحص ما إذا كان الـ origin مسموحاً به (ثابت أو نمط نفق سحابي)."""
    exact = [o for o in settings.CORS_ORIGINS if not o.startswith("https://*.")]
    if origin in exact:
        return True
    return any(p.fullmatch(origin) for p in _TUNNEL_PATTERNS)

# نبني القائمة من الـ origins المحددة (بدون wildcards) + wildcard_origins لمطابقة CORSMiddleware
_static_origins = [o for o in settings.CORS_ORIGINS if not o.startswith("https://*.")]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_static_origins,
    allow_origin_regex=r"https://[a-z0-9\-]+\.(devtunnels\.ms|ngrok\.io|ngrok-free\.app)",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 5. تسجيل مسارات الـ API (دعم بادئة /v1 والبادئة التوافقية /api لضمان التوافق التام مع .NET)
app.include_router(api_router)
app.include_router(api_compat_router)

from src.api.v1.speech import router as speech_router
app.include_router(speech_router)

from src.api.v1.erp import router as erp_router
app.include_router(erp_router)

@app.get("/health", tags=["System"])
async def health_check():
    return {"status": "ok", "environment": settings.ENVIRONMENT}

@app.get("/ready", tags=["System"])
@app.get("/v1/ready", tags=["System"])
@app.get("/api/ready", tags=["System"])
async def readiness_check():
    """
    Readiness Probe:
    Returns 200 OK only after Lifespan completes model warm-up, DB pooling, and Qdrant readiness.
    Returns 503 Service Unavailable if the engine is still starting up.
    """
    if not getattr(app.state, "is_ready", False):
        return JSONResponse(
            status_code=503,
            content={
                "status": "warming_up",
                "ready": False,
                "message": "AI Engine is warming up, loading models and connecting to vector database...",
            }
        )
    return {
        "status": "ready",
        "ready": True,
        "startup_duration_seconds": getattr(app.state, "startup_duration", 0),
        "gemini_model": settings.GEMINI_MODEL,
        "environment": settings.ENVIRONMENT,
    }

# 6. إعداد مقاييس المراقبة الحية (Prometheus Metrics)
from src.core.metrics import init_metrics
init_metrics(app)

from fastapi import FastAPI
from src.core.config import settings
from src.core.logging import setup_logging
from src.api.v1.router import router as api_router

# 1. تهيئة الـ Logging الموحد للنظام
setup_logging()

# 2. إنشاء تطبيق FastAPI
app = FastAPI(
    title=settings.PROJECT_NAME,
    description="LMS AI Co-Pilot API Engine",
    version="1.0.0"
)

# 3. تسجيل مسارات الـ API
app.include_router(api_router)

@app.get("/health", tags=["System"])
async def health_check():
    return {"status": "ok", "environment": settings.ENVIRONMENT}


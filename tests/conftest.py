import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from src.main import app

@pytest_asyncio.fixture(scope="module")
async def async_client():
    # 🚨 تشغيل الـ Lifespan (لإنشاء الـ db_pool) قبل بدء الاختبار
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://localhost"
        ) as client:
            yield client


import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_check(async_client: AsyncClient):
    response = await async_client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_start_audio_ingestion_requires_auth(async_client: AsyncClient):
    """
    بدون توكن → 401. يُثبت أن الـ endpoint محمي بعد إضافة RBAC.
    الاختبار الكامل للـ admin يوجد في tests/integration/test_auth_rbac.py
    """
    payload = {
        "youtube_url": "https://youtu.be/dummy?t=0s",
        "lesson_id": "test_lesson_123"
    }
    response = await async_client.post("/v1/ingest/audio", json=payload)
    assert response.status_code == 401

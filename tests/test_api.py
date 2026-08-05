import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_health_check(async_client: AsyncClient):
    response = await async_client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"

@pytest.mark.asyncio
async def test_start_audio_ingestion(async_client: AsyncClient):
    payload = {
        "youtube_url": "https://youtu.be/dummy?t=0s",
        "lesson_id": "test_lesson_123"
    }
    response = await async_client.post("/v1/ingest/audio", json=payload)
    assert response.status_code == 200
    assert response.json()["status"] == "processing_started"
    assert "sess_test_lesson_123" in response.json()["session_id"]

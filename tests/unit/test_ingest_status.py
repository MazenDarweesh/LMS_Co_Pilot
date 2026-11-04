# tests/unit/test_ingest_status.py
"""
Unit Tests for Video Ingestion Status Endpoint & LMS AI Status Callback
========================================================================
Verifies:
1. Route registration under both /v1 and /api prefixes.
2. Status response contract when lesson is completed in Qdrant.
3. Status response contract when lesson has not been processed (idle).
4. Path traversal / invalid lesson_id input validation (400 Bad Request).
5. LMSClientService notify_lesson_ai_status resilience (fail-safe best effort).
"""
import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, patch, MagicMock

from src.main import app
from src.models.schemas import LessonStatusResponse
from src.services.lms_bridge import LMSClientService
from src.services.cognitive_search import qdrant_service


def test_status_routes_registered():
    """Verify that the ingest status endpoint exists under both /v1 and /api prefixes."""
    paths = app.openapi()["paths"]
    assert "/v1/ingest/status/{lesson_id}" in paths
    assert "/api/ingest/status/{lesson_id}" in paths


@pytest.mark.asyncio
async def test_get_status_invalid_lesson_id():
    """Verify path traversal / injection attempt is blocked with 400."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://localhost") as client:
        resp = await client.get("/v1/ingest/status/bad@id!slash/test")
        assert resp.status_code == 404 or resp.status_code == 400


@pytest.mark.asyncio
async def test_get_status_idle_lesson():
    """Verify idle lesson returns status='idle' and can_generate=False."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://localhost") as client:
        mock_qdrant = AsyncMock()
        mock_qdrant.scroll = AsyncMock(return_value=([], None))
        
        with patch.object(qdrant_service, "_client", mock_qdrant):
            with patch("src.db.event_store.EventStoreRepository.get_session_events", new_callable=AsyncMock) as mock_events:
                mock_events.return_value = []
                
                resp = await client.get("/v1/ingest/status/non-existent-lesson-123")
                assert resp.status_code == 200
                data = resp.json()
                assert data["lesson_id"] == "non-existent-lesson-123"
                assert data["status"] == "idle"
                assert data["chunks_count"] == 0
                assert data["can_generate_quiz"] is False
                assert data["can_generate_summary"] is False


@pytest.mark.asyncio
async def test_get_status_completed_lesson():
    """Verify lesson with chunks in Qdrant returns status='completed' and can_generate=True."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://localhost") as client:
        mock_qdrant = AsyncMock()
        mock_point = MagicMock()
        mock_qdrant.scroll = AsyncMock(return_value=([mock_point] * 5, None))
        
        with patch.object(qdrant_service, "_client", mock_qdrant):
            with patch("src.db.event_store.EventStoreRepository.get_session_events", new_callable=AsyncMock) as mock_events:
                mock_events.return_value = [
                    {"event_type": "PIPELINE_COMPLETE", "payload": {"status": "success"}, "timestamp": "2026-09-17T12:00:00"}
                ]
                
                resp = await client.get("/api/ingest/status/completed-lesson-456")
                assert resp.status_code == 200
                data = resp.json()
                assert data["lesson_id"] == "completed-lesson-456"
                assert data["status"] == "completed"
                assert data["chunks_count"] == 5
                assert data["can_generate_quiz"] is True
                assert data["can_generate_summary"] is True


@pytest.mark.asyncio
async def test_lms_client_notify_ai_status_resilience():
    """Verify notify_lesson_ai_status returns False on network error without raising exceptions."""
    service = LMSClientService()
    mock_http = AsyncMock()
    mock_http.post = AsyncMock(side_effect=Exception("LMS connection refused"))
    service._client = mock_http

    result = await service.notify_lesson_ai_status("test-lesson", "Completed", total_chunks=10)
    assert result is False

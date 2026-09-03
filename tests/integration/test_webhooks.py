# tests/integration/test_webhooks.py
"""
Integration Tests — Webhook Endpoint (Lesson Updated / Deleted)
===============================================================
يختبر: Service Token validation، Accepted responses، Invalid actions.
تشغيل: uv run pytest tests/integration/test_webhooks.py -v
"""
import pytest
from httpx import AsyncClient

from src.core.config import settings

WEBHOOK_URL = "/v1/webhooks/lesson-updated"
VALID_TOKEN_HEADERS = {"X-Service-Token": settings.SERVICE_TOKEN}
INVALID_TOKEN_HEADERS = {"X-Service-Token": "definitely-wrong-token"}


# ─── Service Token Validation ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_webhook_rejects_missing_token(async_client: AsyncClient):
    """بدون X-Service-Token header → 422 (Header مطلوب)."""
    resp = await async_client.post(
        WEBHOOK_URL,
        json={"lessonId": "lesson-001", "action": "Deleted"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_webhook_rejects_invalid_token(async_client: AsyncClient):
    """Service Token خاطئ → 401."""
    resp = await async_client.post(
        WEBHOOK_URL,
        headers=INVALID_TOKEN_HEADERS,
        json={"lessonId": "lesson-001", "action": "Deleted"},
    )
    assert resp.status_code == 401


# ─── Valid Actions ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_webhook_delete_returns_202(async_client: AsyncClient):
    """
    Webhook بـ action=Deleted + Service Token صحيح → 202 Accepted.
    يتم مسح vectors في الخلفية.
    """
    resp = await async_client.post(
        WEBHOOK_URL,
        headers=VALID_TOKEN_HEADERS,
        json={"lessonId": "lesson-nonexistent-for-test", "action": "Deleted"},
    )
    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == "accepted"


@pytest.mark.asyncio
async def test_webhook_delete_response_has_message(async_client: AsyncClient):
    """Webhook delete response يجب أن يحتوي على 'message' field."""
    resp = await async_client.post(
        WEBHOOK_URL,
        headers=VALID_TOKEN_HEADERS,
        json={"lessonId": "lesson-test-msg", "action": "Deleted"},
    )
    assert resp.status_code == 202
    assert "message" in resp.json()


@pytest.mark.asyncio
async def test_webhook_updated_returns_202(async_client: AsyncClient):
    """
    Webhook بـ action=Updated → 202 Accepted.
    يبدأ re-ingestion في الخلفية.
    ملاحظة: قد يفشل الـ Background Task لو LMS مش موجود — لكن الـ Endpoint نفسه 202.
    """
    resp = await async_client.post(
        WEBHOOK_URL,
        headers=VALID_TOKEN_HEADERS,
        json={"lessonId": "lesson-update-test", "action": "Updated"},
    )
    assert resp.status_code == 202
    assert resp.json()["status"] == "accepted"


# ─── Invalid Actions ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_webhook_invalid_action_returns_400(async_client: AsyncClient):
    """action غير معروف → 400 Bad Request."""
    resp = await async_client.post(
        WEBHOOK_URL,
        headers=VALID_TOKEN_HEADERS,
        json={"lessonId": "lesson-001", "action": "SomeRandomAction"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_webhook_missing_lesson_id_returns_422(async_client: AsyncClient):
    """lessonId ناقص → 422 Unprocessable Entity."""
    resp = await async_client.post(
        WEBHOOK_URL,
        headers=VALID_TOKEN_HEADERS,
        json={"action": "Deleted"},  # لا lessonId
    )
    assert resp.status_code == 422

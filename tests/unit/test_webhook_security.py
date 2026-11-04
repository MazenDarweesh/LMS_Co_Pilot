# tests/unit/test_webhook_security.py
"""
Unit Tests for Stripe/GitHub Standard HMAC-SHA256 Webhook Verification
========================================================================
Validates:
1. Valid HMAC-SHA256 signature with current timestamp (Passes).
2. Anti-Replay attack prevention: Rejects timestamps older or newer than 300s (401).
3. Payload integrity: Rejects tampered payloads or modified bytes (403).
4. Secret isolation: Rejects signatures created with an invalid key (403).
5. Non-numeric timestamp header format rejected (401).
6. Missing required signature or timestamp headers rejected (401).
"""
import hmac
import hashlib
import time
import pytest
from unittest.mock import AsyncMock
from fastapi import HTTPException

from src.core.config import settings
from src.services.shared_infrastructure import verify_webhook_signature


def _compute_signature(secret: str, timestamp: str, body: bytes) -> str:
    """Helper to compute HMAC-SHA256 signature matching .NET WebhookDispatcher."""
    payload_to_sign = f"{timestamp}.".encode("utf-8") + body
    return hmac.new(secret.encode("utf-8"), payload_to_sign, hashlib.sha256).hexdigest().lower()


@pytest.mark.asyncio
async def test_valid_hmac_signature():
    """Valid HMAC signature + current timestamp should verify successfully."""
    raw_body = b'{"lessonId":"ab050f42-2584-491b-8f46-25c70a9ccb9a","action":"updated"}'
    ts = str(int(time.time()))
    sig = _compute_signature(settings.LMS_WEBHOOK_SECRET, ts, raw_body)

    mock_request = AsyncMock()
    mock_request.body.return_value = raw_body

    verified = await verify_webhook_signature(
        request=mock_request,
        x_signature_256=f"sha256={sig}",
        x_timestamp=ts,
    )
    assert verified is True


@pytest.mark.asyncio
async def test_replay_attack_expired_timestamp():
    """Timestamp older than 300 seconds must be rejected with 401."""
    raw_body = b'{"lessonId":"ab050f42-2584-491b-8f46-25c70a9ccb9a","action":"updated"}'
    expired_ts = str(int(time.time()) - 301)
    sig = _compute_signature(settings.LMS_WEBHOOK_SECRET, expired_ts, raw_body)

    mock_request = AsyncMock()
    mock_request.body.return_value = raw_body

    with pytest.raises(HTTPException) as exc_info:
        await verify_webhook_signature(
            request=mock_request,
            x_signature_256=sig,
            x_timestamp=expired_ts,
        )
    assert exc_info.value.status_code == 401
    assert "replay attack" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_tampered_payload_rejected():
    """Payload modified in transit must fail HMAC check with 403."""
    original_body = b'{"lessonId":"ab050f42-2584-491b-8f46-25c70a9ccb9a","action":"updated"}'
    ts = str(int(time.time()))
    sig = _compute_signature(settings.LMS_WEBHOOK_SECRET, ts, original_body)

    tampered_body = b'{"lessonId":"ab050f42-2584-491b-8f46-25c70a9ccb9a","action":"deleted"}'
    mock_request = AsyncMock()
    mock_request.body.return_value = tampered_body

    with pytest.raises(HTTPException) as exc_info:
        await verify_webhook_signature(
            request=mock_request,
            x_signature_256=sig,
            x_timestamp=ts,
        )
    assert exc_info.value.status_code == 403
    assert "Invalid webhook signature" in exc_info.value.detail


@pytest.mark.asyncio
async def test_invalid_secret_rejected():
    """Signature generated with wrong secret must be rejected with 403."""
    raw_body = b'{"lessonId":"ab050f42-2584-491b-8f46-25c70a9ccb9a","action":"updated"}'
    ts = str(int(time.time()))
    sig = _compute_signature("wrong_secret_key_123", ts, raw_body)

    mock_request = AsyncMock()
    mock_request.body.return_value = raw_body

    with pytest.raises(HTTPException) as exc_info:
        await verify_webhook_signature(
            request=mock_request,
            x_signature_256=sig,
            x_timestamp=ts,
        )
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_missing_signature_headers_rejected():
    """Requests missing signature or timestamp headers must be rejected with 401."""
    mock_request = AsyncMock()

    # Both missing
    with pytest.raises(HTTPException) as exc_info:
        await verify_webhook_signature(
            request=mock_request,
            x_signature_256=None,
            x_timestamp=None,
        )
    assert exc_info.value.status_code == 401

    # Timestamp missing
    with pytest.raises(HTTPException) as exc_info:
        await verify_webhook_signature(
            request=mock_request,
            x_signature_256="some_signature",
            x_timestamp=None,
        )
    assert exc_info.value.status_code == 401

    # Signature missing
    with pytest.raises(HTTPException) as exc_info:
        await verify_webhook_signature(
            request=mock_request,
            x_signature_256=None,
            x_timestamp=str(int(time.time())),
        )
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_invalid_timestamp_format():
    """Non-numeric timestamp header must be rejected with 401."""
    mock_request = AsyncMock()
    with pytest.raises(HTTPException) as exc_info:
        await verify_webhook_signature(
            request=mock_request,
            x_signature_256="some_signature",
            x_timestamp="not-a-number",
        )
    assert exc_info.value.status_code == 401
    assert "Invalid X-Timestamp header" in exc_info.value.detail


if __name__ == "__main__":
    import asyncio
    print("Running webhook security tests (Strict HMAC-SHA256)...")
    asyncio.run(test_valid_hmac_signature())
    print("1. test_valid_hmac_signature passed [OK]")
    asyncio.run(test_replay_attack_expired_timestamp())
    print("2. test_replay_attack_expired_timestamp passed [OK]")
    asyncio.run(test_tampered_payload_rejected())
    print("3. test_tampered_payload_rejected passed [OK]")
    asyncio.run(test_invalid_secret_rejected())
    print("4. test_invalid_secret_rejected passed [OK]")
    asyncio.run(test_missing_signature_headers_rejected())
    print("5. test_missing_signature_headers_rejected passed [OK]")
    asyncio.run(test_invalid_timestamp_format())
    print("6. test_invalid_timestamp_format passed [OK]")
    print("ALL 6 STRICT WEBHOOK SECURITY TESTS PASSED SUCCESSFULLY! [OK]")

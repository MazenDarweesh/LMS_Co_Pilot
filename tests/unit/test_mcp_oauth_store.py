"""
Unit tests for `src/services/erp_copilot/mcp/oauth_store.py`.
Covers:
- Missing / empty / invalid encryption key failure (`McpEncryptionKeyError`)
- Fernet encryption/decryption roundtrip (ciphertext does not contain plaintext secrets)
- Cross-tenant and cross-user isolation (including ciphertext swap tampering)
- PKCE state lifecycle (create, single-use consume, expiry, cross-user/tenant protection)
- Secret redaction in repr/str
"""

from datetime import datetime, timedelta, timezone
from cryptography.fernet import Fernet
import pytest

from src.services.erp_copilot.mcp.oauth_store import (
    InMemoryMcpOAuthRepository,
    McpEncryptionKeyError,
    McpOAuthIsolationError,
    McpOAuthStoreService,
    McpTokenDecryptionError,
)


def _new_fernet_key() -> str:
    return Fernet.generate_key().decode("utf-8")


def test_missing_or_invalid_encryption_key_raises():
    service = McpOAuthStoreService()

    with pytest.raises(McpEncryptionKeyError):
        service.initialize(encryption_key="")

    with pytest.raises(McpEncryptionKeyError):
        service.initialize(encryption_key="   ")

    with pytest.raises(McpEncryptionKeyError):
        service.initialize(encryption_key="not-a-valid-fernet-key")


@pytest.mark.asyncio
async def test_token_encryption_roundtrip_and_ciphertext_opacity():
    repo = InMemoryMcpOAuthRepository()
    service = McpOAuthStoreService()
    service.initialize(encryption_key=_new_fernet_key(), repository=repo)

    access_secret = "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.super-secret-access"
    refresh_secret = "rt_super_secret_refresh_value"
    expires_at = datetime.now(timezone.utc) + timedelta(hours=1)

    stored = await service.save_tokens(
        "tenant-alpha",
        "user-101",
        access_secret,
        refresh_token=refresh_secret,
        scope="erp.read",
        expires_at=expires_at,
    )

    assert access_secret not in repr(stored)
    assert refresh_secret not in repr(stored)
    assert access_secret not in str(stored)

    raw_ciphertext = await repo.get_token("tenant-alpha", "user-101")
    assert raw_ciphertext is not None
    assert access_secret not in raw_ciphertext
    assert refresh_secret not in raw_ciphertext

    loaded = await service.get_tokens("tenant-alpha", "user-101")
    assert loaded is not None
    assert loaded.tenant_id == "tenant-alpha"
    assert loaded.user_id == "user-101"
    assert loaded.access_token == access_secret
    assert loaded.refresh_token == refresh_secret
    assert loaded.scope == "erp.read"

    assert await service.delete_tokens("tenant-alpha", "user-101") is True
    assert await service.delete_tokens("tenant-alpha", "user-101") is False
    assert await service.get_tokens("tenant-alpha", "user-101") is None


@pytest.mark.asyncio
async def test_cross_user_and_cross_tenant_isolation():
    repo = InMemoryMcpOAuthRepository()
    service = McpOAuthStoreService()
    service.initialize(encryption_key=_new_fernet_key(), repository=repo)

    await service.save_tokens("tenant-a", "user-1", "token-a-1")
    await service.save_tokens("tenant-a", "user-2", "token-a-2")
    await service.save_tokens("tenant-b", "user-1", "token-b-1")

    assert (await service.get_tokens("tenant-a", "user-1")).access_token == "token-a-1"
    assert (await service.get_tokens("tenant-a", "user-2")).access_token == "token-a-2"
    assert (await service.get_tokens("tenant-b", "user-1")).access_token == "token-b-1"
    assert await service.get_tokens("tenant-b", "user-2") is None

    # Simulate DB row swap attack: copy (tenant-a, user-1) ciphertext into (tenant-b, user-2)
    stolen_ciphertext = await repo.get_token("tenant-a", "user-1")
    assert stolen_ciphertext is not None
    await repo.upsert_token("tenant-b", "user-2", stolen_ciphertext, None)

    with pytest.raises(McpOAuthIsolationError):
        await service.get_tokens("tenant-b", "user-2")


@pytest.mark.asyncio
async def test_wrong_key_cannot_decrypt_tokens():
    repo = InMemoryMcpOAuthRepository()
    writer = McpOAuthStoreService()
    writer.initialize(encryption_key=_new_fernet_key(), repository=repo)
    await writer.save_tokens("tenant-a", "user-1", "secret-token")

    reader = McpOAuthStoreService()
    reader.initialize(encryption_key=_new_fernet_key(), repository=repo)
    with pytest.raises(McpTokenDecryptionError):
        await reader.get_tokens("tenant-a", "user-1")


@pytest.mark.asyncio
async def test_pkce_state_lifecycle_and_isolation():
    repo = InMemoryMcpOAuthRepository()
    service = McpOAuthStoreService()
    service.initialize(encryption_key=_new_fernet_key(), repository=repo)

    pkce = await service.create_pkce_state(
        "tenant-a",
        "user-1",
        "verifier-secret-12345",
        "http://localhost:8000/callback",
        ttl_seconds=300,
    )
    assert "verifier-secret-12345" not in repr(pkce)

    # Another user or tenant cannot consume the state
    assert await service.consume_pkce_state(pkce.state, "tenant-a", "user-2") is None
    assert await service.consume_pkce_state(pkce.state, "tenant-b", "user-1") is None

    # Rightful owner consumes it once
    consumed = await service.consume_pkce_state(pkce.state, "tenant-a", "user-1")
    assert consumed is not None
    assert consumed.code_verifier == "verifier-secret-12345"
    assert consumed.redirect_uri == "http://localhost:8000/callback"

    # Replay is rejected
    assert await service.consume_pkce_state(pkce.state, "tenant-a", "user-1") is None

    # Expired state is rejected
    expired = await service.create_pkce_state(
        "tenant-a",
        "user-1",
        "verifier-expired",
        "http://localhost:8000/callback",
        ttl_seconds=1,
    )
    # Force expiry in repo
    stored = repo._pkce_states[expired.state]
    repo._pkce_states[expired.state] = (
        stored[0],
        stored[1],
        stored[2],
        datetime.now(timezone.utc) - timedelta(seconds=5),
    )
    assert await service.consume_pkce_state(expired.state, "tenant-a", "user-1") is None

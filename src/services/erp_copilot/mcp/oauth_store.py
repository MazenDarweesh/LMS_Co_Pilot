"""
Encrypted Per-User MCP OAuth Token & PKCE State Store
=====================================================
Provides Fernet-authenticated encryption for per-(tenant_id, user_id) MCP OAuth
tokens and short-lived PKCE authorization states.

Design:
- Pluggable `McpOAuthRepository` protocol with `PostgresMcpOAuthRepository`
  (asyncpg, parameterized queries) and `InMemoryMcpOAuthRepository` (for unit tests).
- Strict tenant + user isolation at both the repository key/query level and
  inside the encrypted payload envelope (binding ciphertext to tenant_id + user_id).
- Fails closed with `McpEncryptionKeyError` if `MCP_TOKEN_ENCRYPTION_KEY` is
  missing, empty, or not a valid Fernet key.
- Zero secret leakage in logs, exceptions, or object representations.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import secrets
from typing import Any, Protocol, runtime_checkable

import asyncpg
from cryptography.fernet import Fernet, InvalidToken
from pydantic import BaseModel, Field
import structlog

from src.core.config import settings

logger = structlog.get_logger()


CREATE_MCP_OAUTH_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS mcp_oauth_tokens (
    tenant_id VARCHAR(64) NOT NULL,
    user_id VARCHAR(128) NOT NULL,
    encrypted_payload TEXT NOT NULL,
    expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (tenant_id, user_id)
);

CREATE TABLE IF NOT EXISTS mcp_oauth_pkce_states (
    state VARCHAR(256) PRIMARY KEY,
    tenant_id VARCHAR(64) NOT NULL,
    user_id VARCHAR(128) NOT NULL,
    encrypted_payload TEXT NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_mcp_oauth_pkce_expires_at
    ON mcp_oauth_pkce_states(expires_at);
"""


class McpEncryptionKeyError(RuntimeError):
    """Raised when MCP_TOKEN_ENCRYPTION_KEY is missing, empty, or invalid."""


class McpTokenDecryptionError(RuntimeError):
    """Raised when stored ciphertext cannot be decrypted or fails integrity checks."""


class McpOAuthIsolationError(RuntimeError):
    """Raised when decrypted payload tenant/user binding does not match the caller."""


class McpOAuthTokenRecord(BaseModel):
    """Decrypted OAuth token bundle for a single (tenant_id, user_id)."""

    tenant_id: str
    user_id: str
    access_token: str = Field(repr=False)
    refresh_token: str | None = Field(default=None, repr=False)
    token_type: str = "Bearer"
    scope: str | None = None
    expires_at: datetime | None = None
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def __repr__(self) -> str:
        return (
            f"McpOAuthTokenRecord(tenant_id={self.tenant_id!r}, "
            f"user_id={self.user_id!r}, token_type={self.token_type!r}, "
            f"access_token='[REDACTED]', has_refresh={self.refresh_token is not None})"
        )

    def __str__(self) -> str:
        return self.__repr__()


class McpPkceStateRecord(BaseModel):
    """Decrypted PKCE state bundle bound to a single (tenant_id, user_id)."""

    state: str
    tenant_id: str
    user_id: str
    code_verifier: str = Field(repr=False)
    redirect_uri: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime

    def __repr__(self) -> str:
        return (
            f"McpPkceStateRecord(tenant_id={self.tenant_id!r}, "
            f"user_id={self.user_id!r}, code_verifier='[REDACTED]', "
            f"expires_at={self.expires_at.isoformat()!r})"
        )

    def __str__(self) -> str:
        return self.__repr__()


@runtime_checkable
class McpOAuthRepository(Protocol):
    """Persistence contract for encrypted MCP OAuth tokens and PKCE states."""

    async def upsert_token(
        self,
        tenant_id: str,
        user_id: str,
        encrypted_payload: str,
        expires_at: datetime | None,
    ) -> None: ...

    async def get_token(self, tenant_id: str, user_id: str) -> str | None: ...

    async def delete_token(self, tenant_id: str, user_id: str) -> bool: ...

    async def save_pkce_state(
        self,
        state: str,
        tenant_id: str,
        user_id: str,
        encrypted_payload: str,
        expires_at: datetime,
    ) -> None: ...

    async def consume_pkce_state(
        self,
        state: str,
        tenant_id: str,
        user_id: str,
    ) -> str | None: ...


class InMemoryMcpOAuthRepository:
    """In-memory repository implementation for unit testing and isolated runs."""

    def __init__(self) -> None:
        self._tokens: dict[tuple[str, str], str] = {}
        self._pkce_states: dict[str, tuple[str, str, str, datetime]] = {}

    async def upsert_token(
        self,
        tenant_id: str,
        user_id: str,
        encrypted_payload: str,
        expires_at: datetime | None,
    ) -> None:
        self._tokens[(tenant_id, user_id)] = encrypted_payload

    async def get_token(self, tenant_id: str, user_id: str) -> str | None:
        return self._tokens.get((tenant_id, user_id))

    async def delete_token(self, tenant_id: str, user_id: str) -> bool:
        return self._tokens.pop((tenant_id, user_id), None) is not None

    async def save_pkce_state(
        self,
        state: str,
        tenant_id: str,
        user_id: str,
        encrypted_payload: str,
        expires_at: datetime,
    ) -> None:
        self._pkce_states[state] = (tenant_id, user_id, encrypted_payload, expires_at)

    async def consume_pkce_state(
        self,
        state: str,
        tenant_id: str,
        user_id: str,
    ) -> str | None:
        entry = self._pkce_states.get(state)
        if entry is None:
            return None
        stored_tenant, stored_user, encrypted_payload, expires_at = entry
        if stored_tenant != tenant_id or stored_user != user_id:
            return None
        self._pkce_states.pop(state, None)
        if expires_at <= datetime.now(timezone.utc):
            return None
        return encrypted_payload


class PostgresMcpOAuthRepository:
    """PostgreSQL-backed repository using asyncpg parameterized queries."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def ensure_schema(self) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(CREATE_MCP_OAUTH_TABLES_SQL)

    async def upsert_token(
        self,
        tenant_id: str,
        user_id: str,
        encrypted_payload: str,
        expires_at: datetime | None,
    ) -> None:
        sql = """
            INSERT INTO mcp_oauth_tokens (
                tenant_id, user_id, encrypted_payload, expires_at, updated_at
            ) VALUES ($1, $2, $3, $4, NOW())
            ON CONFLICT (tenant_id, user_id) DO UPDATE SET
                encrypted_payload = EXCLUDED.encrypted_payload,
                expires_at = EXCLUDED.expires_at,
                updated_at = NOW()
        """
        async with self._pool.acquire() as conn:
            await conn.execute(sql, tenant_id, user_id, encrypted_payload, expires_at)

    async def get_token(self, tenant_id: str, user_id: str) -> str | None:
        sql = """
            SELECT encrypted_payload
            FROM mcp_oauth_tokens
            WHERE tenant_id = $1 AND user_id = $2
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(sql, tenant_id, user_id)
        return str(row["encrypted_payload"]) if row else None

    async def delete_token(self, tenant_id: str, user_id: str) -> bool:
        sql = """
            DELETE FROM mcp_oauth_tokens
            WHERE tenant_id = $1 AND user_id = $2
        """
        async with self._pool.acquire() as conn:
            status = await conn.execute(sql, tenant_id, user_id)
        return status.endswith("1")

    async def save_pkce_state(
        self,
        state: str,
        tenant_id: str,
        user_id: str,
        encrypted_payload: str,
        expires_at: datetime,
    ) -> None:
        sql = """
            INSERT INTO mcp_oauth_pkce_states (
                state, tenant_id, user_id, encrypted_payload, expires_at
            ) VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (state) DO UPDATE SET
                tenant_id = EXCLUDED.tenant_id,
                user_id = EXCLUDED.user_id,
                encrypted_payload = EXCLUDED.encrypted_payload,
                expires_at = EXCLUDED.expires_at
        """
        async with self._pool.acquire() as conn:
            await conn.execute(sql, state, tenant_id, user_id, encrypted_payload, expires_at)

    async def consume_pkce_state(
        self,
        state: str,
        tenant_id: str,
        user_id: str,
    ) -> str | None:
        sql = """
            DELETE FROM mcp_oauth_pkce_states
            WHERE state = $1
              AND tenant_id = $2
              AND user_id = $3
              AND expires_at > NOW()
            RETURNING encrypted_payload
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(sql, state, tenant_id, user_id)
        return str(row["encrypted_payload"]) if row else None


class McpOAuthStoreService:
    """
    Singleton service managing encrypted per-(tenant_id, user_id) MCP OAuth tokens
    and PKCE authorization states.
    """

    def __init__(self) -> None:
        self._fernet: Fernet | None = None
        self._repo: McpOAuthRepository | None = None

    def initialize(
        self,
        *,
        encryption_key: str | None = None,
        pool: asyncpg.Pool | None = None,
        repository: McpOAuthRepository | None = None,
    ) -> None:
        """
        Initializes Fernet cipher and repository backend.
        Raises `McpEncryptionKeyError` if the key is missing or invalid.
        """
        raw_key = settings.MCP_TOKEN_ENCRYPTION_KEY if encryption_key is None else encryption_key
        if not raw_key or not raw_key.strip():
            raise McpEncryptionKeyError(
                "MCP_TOKEN_ENCRYPTION_KEY is missing or empty; cannot initialize MCP OAuth store."
            )

        try:
            self._fernet = Fernet(raw_key.strip().encode("utf-8"))
        except (ValueError, TypeError) as exc:
            raise McpEncryptionKeyError(
                "MCP_TOKEN_ENCRYPTION_KEY is invalid; expected a 32-byte URL-safe base64 Fernet key."
            ) from exc

        if repository is not None:
            self._repo = repository
        elif pool is not None:
            self._repo = PostgresMcpOAuthRepository(pool)
        else:
            self._repo = InMemoryMcpOAuthRepository()

        logger.info(
            "MCP OAuth store service ready ✅",
            repository_type=type(self._repo).__name__,
        )

    def _require_ready(self) -> tuple[Fernet, McpOAuthRepository]:
        if self._fernet is None or self._repo is None:
            raise RuntimeError("McpOAuthStoreService not initialized; call initialize() first.")
        return self._fernet, self._repo

    @staticmethod
    def _validate_scope(tenant_id: str, user_id: str) -> tuple[str, str]:
        t_id = tenant_id.strip()
        u_id = user_id.strip()
        if not t_id or not u_id:
            raise ValueError("tenant_id and user_id must be non-empty strings.")
        return t_id, u_id

    def _encrypt_envelope(self, fernet: Fernet, tenant_id: str, user_id: str, payload: dict[str, Any]) -> str:
        envelope = {
            "_tenant_id": tenant_id,
            "_user_id": user_id,
            "payload": payload,
        }
        raw = json.dumps(envelope, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        return fernet.encrypt(raw).decode("utf-8")

    def _decrypt_envelope(
        self,
        fernet: Fernet,
        ciphertext: str,
        expected_tenant_id: str,
        expected_user_id: str,
    ) -> dict[str, Any]:
        try:
            plaintext = fernet.decrypt(ciphertext.encode("utf-8"))
            envelope = json.loads(plaintext.decode("utf-8"))
        except (InvalidToken, ValueError, UnicodeDecodeError) as exc:
            raise McpTokenDecryptionError("Failed to decrypt MCP OAuth payload.") from exc

        if (
            envelope.get("_tenant_id") != expected_tenant_id
            or envelope.get("_user_id") != expected_user_id
        ):
            raise McpOAuthIsolationError(
                "Decrypted MCP OAuth payload does not match requested (tenant_id, user_id)."
            )
        payload = envelope.get("payload")
        if not isinstance(payload, dict):
            raise McpTokenDecryptionError("Malformed decrypted MCP OAuth payload.")
        return payload

    async def save_tokens(
        self,
        tenant_id: str,
        user_id: str,
        access_token: str,
        *,
        refresh_token: str | None = None,
        token_type: str = "Bearer",
        scope: str | None = None,
        expires_at: datetime | None = None,
    ) -> McpOAuthTokenRecord:
        """Encrypts and persists OAuth tokens for (tenant_id, user_id)."""
        fernet, repo = self._require_ready()
        t_id, u_id = self._validate_scope(tenant_id, user_id)
        if not access_token or not access_token.strip():
            raise ValueError("access_token must be non-empty.")

        record = McpOAuthTokenRecord(
            tenant_id=t_id,
            user_id=u_id,
            access_token=access_token.strip(),
            refresh_token=refresh_token.strip() if refresh_token else None,
            token_type=token_type,
            scope=scope,
            expires_at=expires_at,
            updated_at=datetime.now(timezone.utc),
        )
        ciphertext = self._encrypt_envelope(fernet, t_id, u_id, record.model_dump(mode="json"))
        await repo.upsert_token(t_id, u_id, ciphertext, expires_at)
        logger.info("MCP OAuth token stored", tenant_id=t_id, user_id=u_id)
        return record

    async def get_tokens(self, tenant_id: str, user_id: str) -> McpOAuthTokenRecord | None:
        """Retrieves and decrypts OAuth tokens for (tenant_id, user_id)."""
        fernet, repo = self._require_ready()
        t_id, u_id = self._validate_scope(tenant_id, user_id)
        ciphertext = await repo.get_token(t_id, u_id)
        if ciphertext is None:
            return None
        payload = self._decrypt_envelope(fernet, ciphertext, t_id, u_id)
        return McpOAuthTokenRecord.model_validate(payload)

    async def delete_tokens(self, tenant_id: str, user_id: str) -> bool:
        """Deletes stored OAuth tokens for (tenant_id, user_id)."""
        _, repo = self._require_ready()
        t_id, u_id = self._validate_scope(tenant_id, user_id)
        deleted = await repo.delete_token(t_id, u_id)
        logger.info("MCP OAuth token deleted", tenant_id=t_id, user_id=u_id, deleted=deleted)
        return deleted

    async def create_pkce_state(
        self,
        tenant_id: str,
        user_id: str,
        code_verifier: str,
        redirect_uri: str,
        *,
        state: str | None = None,
        ttl_seconds: int = 600,
    ) -> McpPkceStateRecord:
        """Encrypts and stores a short-lived PKCE state bound to (tenant_id, user_id)."""
        fernet, repo = self._require_ready()
        t_id, u_id = self._validate_scope(tenant_id, user_id)
        if not code_verifier or not code_verifier.strip():
            raise ValueError("code_verifier must be non-empty.")

        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=max(ttl_seconds, 1))
        state_token = state.strip() if state else secrets.token_urlsafe(32)

        record = McpPkceStateRecord(
            state=state_token,
            tenant_id=t_id,
            user_id=u_id,
            code_verifier=code_verifier.strip(),
            redirect_uri=redirect_uri,
            created_at=now,
            expires_at=expires_at,
        )
        ciphertext = self._encrypt_envelope(fernet, t_id, u_id, record.model_dump(mode="json"))
        await repo.save_pkce_state(state_token, t_id, u_id, ciphertext, expires_at)
        logger.info("MCP PKCE state created", tenant_id=t_id, user_id=u_id)
        return record

    async def consume_pkce_state(
        self,
        state: str,
        tenant_id: str,
        user_id: str,
    ) -> McpPkceStateRecord | None:
        """Atomically consumes and decrypts a PKCE state if valid and owned by caller."""
        fernet, repo = self._require_ready()
        t_id, u_id = self._validate_scope(tenant_id, user_id)
        if not state or not state.strip():
            return None
        ciphertext = await repo.consume_pkce_state(state.strip(), t_id, u_id)
        if ciphertext is None:
            return None
        payload = self._decrypt_envelope(fernet, ciphertext, t_id, u_id)
        return McpPkceStateRecord.model_validate(payload)

    async def close(self) -> None:
        self._fernet = None
        self._repo = None


# Module-level singleton — initialize() called from lifespan or tests
mcp_oauth_store_service = McpOAuthStoreService()

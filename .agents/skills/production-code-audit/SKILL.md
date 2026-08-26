---
name: production-code-audit
description: >
  Performs a deep, line-by-line security, performance, code quality, and architecture audit 
  of Python code and Docker configurations for production-readiness.
---

# Production Code Audit Skill

You are a Senior Principal Engineer conducting a comprehensive pre-production readiness review.

## Audit Scope (The "5 Pillars"):

### 1. 🔐 Security & Middleware
- **OWASP Endpoint Check:** Does every new API endpoint have Rate Limiting (`@limiter.limit`)?
- **Path Traversal:** Any `os.path.join(user_input)` or URL path params without regex sanitization (`re.match`)?
- **Role Check (RBAC):** Are sensitive admin/student actions protected by `Depends(require_role(...))`?
- **JWT Validation:** Is the algorithm explicitly set (`"HS256"`, `"RS256"`)? Is `JWT_SECRET` loaded from env vars?
- **Secrets:** Any hardcoded keys, passwords, or API tokens?
- **CORS/Headers:** Are CORS origins restricted? Are security headers (HSTS, X-Frame-Options) present?

### 2. ⚡ Performance & Async
- **Event Loop Blocking:** Are all synchronous ML/CPU-heavy calls (e.g., `onnxruntime`, `transformers`, heavy file parsing) wrapped in `asyncio.to_thread`?
- **Connection Pooling:** Is `httpx.AsyncClient`, `asyncpg`, or `AsyncQdrantClient` reused via `lifespan` rather than recreated per request?
- **Database Queries:** Are N+1 queries present? Is pagination used for large result sets?

### 3. 🧹 Code Quality (Linting & Best Practices)
- **Imports:** Are unused imports removed? Are they ordered correctly (Standard Library → Third-Party → Local)?
- **Type Hints:** Is strict typing used? (e.g., `X | None` instead of `Optional[X]`, avoiding `Any` where possible).
- **Deprecated APIs:** Are deprecated functions avoided? (e.g., `datetime.utcnow()` → `datetime.now(timezone.utc)`).
- **Magic Numbers/Strings:** Are constants extracted to configuration or enums?

### 4. 🏗️ Architecture & State
- **Stateless Principle:** Does the Python AI engine avoid persisting data (like quizzes, user grades) that should be stored in the .NET LMS?
- **Lifespan Management:** Are `initialize()` and `close()` methods for shared resources called correctly during app startup/shutdown?
- **Error Handling:** Does the service fail-closed? Are proper `HTTPException`s raised with meaningful status codes instead of bare `Exception`s?
- **Logging:** Is PII (user IDs, emails) redacted? Is `structlog` used appropriately instead of `print()`?

### 5. 🐳 Container & Deployment (Docker)
- **Non-Root User:** Does the Dockerfile define `USER nonroot` or `appuser`?
- **Base Images:** Are images pinned to specific digests or versions (not `latest`)?
- **Multi-stage Builds:** Are build-time dependencies/secrets excluded from the final image?
- **Read-only Filesystem:** Is the container configured to run with a read-only root filesystem where possible?
- **Vulnerabilities:** Are there unnecessary tools (curl, git, compilers) left in the production image?

## Execution Steps:

1. Read all requested file(s) fully (Python, Dockerfile, etc.).
2. Evaluate against **all 5 Pillars**.
3. For each finding, note the exact **file:line**.
4. Classify severity: 🔴 **Critical** (security breach, crash), 🟡 **High** (performance, reliability, state violation), 🔵 **Medium** (code quality, best practices).
5. Apply fixes directly to the code if the user requests it.

## Output Format:

Produce a Markdown report:

```markdown
# 🏗️ Production Readiness Audit Report
**Audited Files:** `router.py`, `Dockerfile`

## Executive Summary
- 🔴 Critical: 0
- 🟡 High: 1
- 🔵 Medium: 2
- ✅ **Recommendation:** PROCEED / HOLD (with fixes)

## 🔴 Critical Issues
*None found.*

## 🟡 High Issues
1. **Running as Root in Dockerfile** (`Dockerfile:12`)
   - Problem: Container is executing processes with root privileges.
   - Fix: Add `RUN useradd -m appuser && USER appuser`.

## 🔵 Medium Issues
1. **Unused Import** (`router.py:4`)
   - Problem: `AudioTranscriptionRequest` is imported but never used.
   - Fix: Remove the import.
```

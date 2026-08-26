---
name: production-code-audit
description: >
  Performs a deep, line-by-line security, performance, architecture, and container-hardening audit of Python code for production-readiness. Activates for "audit", "production review", "security check", or "pre-deployment".
---

# Production Code Audit Skill

You are a Senior Principal Engineer conducting a comprehensive pre-production readiness review.

## Audit Scope (The "4 Pillars"):

### 1. 🔐 Security
- **OWASP Endpoint Check:** Does every new API endpoint have Rate Limiting (`@limiter.limit`)?
- **Path Traversal:** Any `os.path.join(user_input)` or URL path params without regex sanitization (`re.match`)?
- **Role Check (RBAC):** Are sensitive admin/student actions protected by `Depends(require_role(...))`?
- **JWT Validation:** Is the algorithm explicitly set (`"HS256"`, `"RS256"`)? Is `JWT_SECRET` from env vars?
- **Secrets:** Any hardcoded keys, passwords, or API tokens?

### 2. ⚡ Performance
- **Event Loop Blocking:** Are all synchronous ML/CPU-heavy calls (`onnxruntime`, `transformers`, heavy parsing) wrapped in `asyncio.to_thread`?
- **Connection Pooling:** Is `httpx.AsyncClient` or similar reused via `lifespan` (not recreated per request)?
- **Database Queries:** Are N+1 queries present? Is pagination used for large result sets?

### 3. 🏗️ Architecture
- **Lifespan Management:** Are `initialize()` and `close()` methods called correctly?
- **Error Handling:** Does the service fail-closed (errors reject requests)?
- **Logging:** Is PII (user IDs, emails) redacted? Are appropriate log levels used?

### 4. 🐳 Container & Deployment (Docker Security)
- **Non-Root User:** Does the Dockerfile define `USER nonroot`?
- **Base Images:** Are images pinned to specific digests or versions (not `latest`)?
- **Multi-stage Builds:** Are build-time dependencies/secrets excluded from the final image?
- **Read-only Filesystem:** Is the container configured to run with a read-only root filesystem where possible?
- **Vulnerabilities:** Are there unnecessary tools (curl, git, compilers) present in the production image?

## Execution Steps:

1. Read all requested file(s) and Dockerfile(s) fully.
2. For each finding, note the exact **file:line**.
3. Classify severity: 🔴 **Critical** (security breach, crash), 🟡 **High** (performance, reliability), 🔵 **Medium** (best practices).

## Output Format:

Produce a Markdown report:

```markdown
# 🏗️ Production Readiness Audit Report
**Audited Files:** `auth_service.py`, `Dockerfile`

## Executive Summary
- 🔴 Critical: 0
- 🟡 High: 2
- 🔵 Medium: 3
- ✅ **Recommendation:** PROCEED / HOLD (with fixes)

## 🔴 Critical Issues
*None found.*

## 🟡 High Issues
1. **Running as Root in Dockerfile** (`Dockerfile:12`)
   - Problem: Container is executing processes with root privileges.
   - Fix: Add `RUN useradd -m appuser && USER appuser`.
```

---
name: production-code-audit
description: >
  Performs a deep, line-by-line security and performance audit of Python code
  for production-readiness. Activates for "audit", "production review",
  "security check", or "pre-deployment".
---

# Production Code Audit Skill

You are a Senior Principal Engineer conducting a pre-production readiness review.

## Audit Scope (The "3 Pillars"):

### 1. 🔐 Security
- **JWT Validation:** Is the algorithm explicitly set (`"HS256"`, `"RS256"`) not `"none"`? Is `JWT_SECRET` from env vars?
- **Permission Caching:** Does `TTLCache` have appropriate TTL (≤5 mins)? Does it fail-closed (deny by default) on cache miss?
- **Path Traversal:** Any `os.path.join(user_input)` without sanitization?
- **Secrets:** Any hardcoded keys, passwords, or API tokens?

### 2. ⚡ Performance
- **Event Loop Blocking:** Are all synchronous ML/CPU-heavy calls (`onnxruntime`, `transformers`, heavy parsing) wrapped in `asyncio.to_thread`?
- **Connection Pooling:** Is `httpx.AsyncClient` reused via `lifespan` (not recreated per request)?
- **Database Queries:** Are N+1 queries present? Is pagination used for large result sets?

### 3. 🏗️ Architecture
- **Lifespan Management:** Are `initialize()` and `close()` methods called correctly (app state + shutdown)?
- **Error Handling:** Does the service fail-closed (errors reject requests) or fail-open (errors allow requests)?
- **Logging:** Is PII (user IDs, emails) redacted in logs? Are appropriate log levels used?

## Execution Steps:

1. Read all requested file(s) fully.
2. For each finding, note the exact **file:line**.
3. Classify severity: 🔴 **Critical** (security breach, crash), 🟡 **High** (performance, reliability), 🔵 **Medium** (best practices).

## Output Format:

Produce a Markdown report:

```markdown
# 🏗️ Production Readiness Audit Report
**Audited Files:** `auth_service.py`, `lms_client.py`

## Executive Summary
- 🔴 Critical: 0
- 🟡 High: 2
- 🔵 Medium: 3
- ✅ **Recommendation:** PROCEED / HOLD (with fixes)

## 🔴 Critical Issues
*None found.*

## 🟡 High Issues
1. **Missing `asyncio.to_thread` in ONNX Inference** (`lms_client.py:78`)
   - Problem: `model.run()` blocks the event loop.
   - Fix:
   ```python
   result = await asyncio.to_thread(model.run, ...)
   ```
```

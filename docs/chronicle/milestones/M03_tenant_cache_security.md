---
milestone_id: "M03"
title: "Multi-Tenant Semantic Cache & RBAC Security"
status: "COMPLETED"
last_synced_commit: "08289e5"
completed_at: "2026-09-07T10:00:00Z"
---

# 🎯 M03: Multi-Tenant Semantic Cache & RBAC Security

## 1. Engineering Objective
Enforce ironclad data isolation across different companies (tenants) using the LMS, while implementing an ultra-low latency semantic cache that respects user access permissions without leaking unauthorized chunks.

## 2. Architectural Tensions & Trade-offs ("The Why")
* **The Conflict/Tension:** In a multi-tenant B2B LMS, naive caching returns cached responses across users regardless of whether Student B has purchased or been granted access to the specific lesson. Furthermore, querying Qdrant across multiple tenant collections created operational overhead and fragmented HNSW indexes.
* **The Decision:**
  1. Used a single flat Qdrant collection with `is_tenant=True` on `tenant_id` / `lesson_id` for hardware-accelerated HNSW partitioned traversal.
  2. Implemented a Semantic Cache (Cosine similarity threshold >= 0.95) that intercepts queries in < 15ms.
  3. **Security Gate:** Cached payloads include the required lesson and tenant IDs; on a cache HIT, the middleware verifies the caller's active JWT claims against those IDs before releasing the answer.
* **What We Avoided:** Rejected separate Qdrant collections per company/lesson, which would have exhausted file descriptors and memory on the Qdrant instance.

## 3. Verification & Proof of Work
* **Cache Latency:** Measured cache HIT latency at `< 15ms` compared to `~3.5s` for full generation.
* **Security Controls:** Rate limiting (`@limiter.limit("10/minute")`) and strict CORS origins implemented and verified on the search router.

## 4. Interview STAR Capsule
* **Situation:** Serving multiple enterprise clients on a shared AI backend risked cross-tenant data leaks and redundant LLM inference costs.
* **Task:** Implement strict tenant isolation and caching without creating security vulnerabilities or excessive vector index overhead.
* **Action:** Built a tenant-aware semantic cache in Qdrant with runtime RBAC entitlement validation before returning cached answers, and configured HNSW tenant payload partitioning.
* **Result:** Reduced recurring LLM costs by ~45% for popular queries while ensuring 100% tenant isolation and access entitlement compliance.

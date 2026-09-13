---
milestone_id: "M05"
title: "Enterprise .NET ERP Bridge, BOLA Defense & Fast Ingress"
status: "COMPLETED"
last_synced_commit: "d8ce713"
completed_at: "2026-09-13T13:50:00Z"
---

# 🎯 M05: Enterprise .NET ERP Bridge, BOLA Defense & Fast Ingress

## 1. Engineering Objective
Integrate the Python AI engine with the host .NET ERP backend via secured JWT identity propagation and connection-pooled HTTP services, while delivering enterprise-grade security (OWASP BOLA defense, Fail-Closed tenant isolation), two-tier fast ingress caching (<1ms exact + <25ms semantic), and thread-safe per-lesson concurrency locks.

## 2. Architectural Tensions & Trade-offs ("The Why")
* **The Conflict/Tension:** The .NET LMS backend owns the source of truth for user identities, course entitlements, and lesson metadata. The AI engine must never leak checkpoint files across tenant organizations, even under LMS downtime or admin credential abuse. Concurrently, rapid or retry webhooks for the same lesson risked concurrent ingestion execution, chunk duplication, and race conditions.
* **The Decisions:**
  1. **Fail-Closed BOLA Defense:** Enforce strict object-level entitlement checks on `GET /v1/lessons/{lesson_id}`. For students, access is restricted strictly to `accessible_lesson_ids`. For admins, cross-tenant access is validated against `lesson_tenants` fetched from LMS. Under LMS failure, the endpoint strictly rejects access with `503 Service Unavailable`, and rejects unassigned lessons with `403 Forbidden` (Fail-Closed Principle).
  2. **Two-Tier Fast Ingress & Sub-ms Intent Router:** Implemented Tier-1 Exact In-Memory LRU (<1ms) keyed deterministically on 4D SHA-256 (`company:dept:role:query`) to eliminate cross-department cache thrashing, combined with Tier-2 Qdrant Semantic Cache (cosine >= 0.92). Heuristic regex intent router intercepts greetings (Egyptian, Gulf, Levantine dialects) and out-of-scope queries in `< 0.1ms`.
  3. **TOCTOU-Proof Concurrency Serialization (ADR-09):** Serialized lesson re-ingestion via `_get_lesson_ingest_lock(lesson_id)` with a dual-condition bounded pruning mechanism (prunes only if unlocked AND idle > 1h, evicting oldest-idle first) to prevent time-of-check-to-time-of-use lock duplication under 10k churn. Documented single-replica boundary and future PostgreSQL lease table migration for multi-pod deployments.
  4. **Contract Stabilization via Pydantic:** Standardized LMS payload parsing into `LessonFullContext` using `AliasChoices` for seamless .NET PascalCase and camelCase serialization compatibility, with in-memory `TTLCache` (5 min) and immediate webhook invalidation.
* **What We Avoided:** Rejected blind fail-open exception handling on admin checks; rejected `WeakValueDictionary` due to premature garbage collection risks in asyncio; rejected holding open PostgreSQL transactions (`pg_advisory_xact_lock`) for long audio pipelines to avoid connection pool starvation.

## 3. Verification & Proof of Work
* **Contract Specification:** Auth and webhook contracts documented in `docs/LMS_INTEGRATION_CONTRACT.md` and ADR-09 in `docs/production_notes.md`.
* **Execution Blueprint:** Step-by-step PR breakdown detailed in `docs/REMAINING_TASKS_BLUEPRINT.md`.
* **Test Strategy:** 38 unit and integration tests passing in 0.31s (`tests/test_fast_ingress.py`), verifying BOLA enforcement, cross-tenant admin blocking, Fail-Closed error behavior, concurrency serialization, and TOCTOU lock pruning.

## 4. Interview STAR Capsule
* **Situation:** Connecting an autonomous AI microservice to an enterprise ERP exposed endpoints to Broken Object Level Authorization (BOLA), cross-tenant admin data leaks, and race conditions during burst webhooks.
* **Task:** Architect robust multi-tenant authorization, sub-millisecond fast ingress caching, and thread-safe ingestion concurrency controls.
* **Action:** Engineered Fail-Closed BOLA verification, two-tier deterministic 4D caching, an in-memory TTL cache with immediate webhook invalidation, and a per-lesson lock registry protected against TOCTOU race conditions with bounded pruning.
* **Result:** Eliminated 100% of LLM and embedding latency on repetitive queries (<1ms exact hit), prevented cross-tenant leakage with strict 503/403 boundaries, and guaranteed deterministic serialization during lesson re-ingestion.

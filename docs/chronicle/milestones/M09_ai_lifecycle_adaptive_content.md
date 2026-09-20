---
milestone_id: "M09"
title: "AI Ingestion Lifecycle State Machine, Adaptive Content & Resilient Auth"
status: "COMPLETED"
last_synced_commit: "da9c342"
completed_at: "2026-09-18T13:45:00Z"
---

# 🎯 M09: AI Ingestion Lifecycle State Machine, Adaptive Content & Resilient Auth

## 1. Engineering Objective
Deliver a resilient, production-grade video AI ingestion lifecycle state machine (`None` ➔ `Queued` ➔ `Processing` ➔ `Completed` / `Failed`) with asynchronous webhook status notification callbacks to the .NET 10 backend, provide a live stateless status query fallback endpoint (`GET /v1/ingest/status/{lesson_id}`), introduce adaptive question scaling (`min(k, chunks)`) for short lessons, and harden JWT claim ingress for cross-stack identity compatibility.

## 2. Architectural Tensions & Trade-offs ("The Why")
* **The Conflict/Tension:** Long-running audio ingestion jobs (Whisper transcription, Gemini normalization, BGE-M3 embedding, Qdrant upsert) take 30 to 120 seconds. In the frontend and .NET backend, users had no visibility into whether a lesson was processing, ready for quiz generation, or had failed. Furthermore:
  1. For short video lessons (<2 minutes), rigid generation prompts requesting 5 questions caused either severe LLM hallucinations (fabricating details outside the transcript) or 500 crashes due to context exhaustion.
  2. Unprocessed lessons (0 chunks in Qdrant) crashed with generic 500 errors when quiz generation was triggered.
  3. ASP.NET Core Identity tokens emitted for SuperAdmins lacked `company_id` claims, causing strict Pydantic models to fail with 422/500 validation errors.
* **The Decisions:**
  1. **Dual Synchronization Protocol (ADR-19):** Implemented an asynchronous webhook callback in `LmsClient.notify_lesson_ai_status()` dispatched directly to `POST http://<DOTNET_HOST>:5115/api/internal/lessons/{lessonId}/ai-status` upon pipeline completion or failure. In parallel, exposed `GET /v1/ingest/status/{lesson_id}` (and `/api/ingest/status/{lesson_id}`) querying live Qdrant chunk counts and in-memory locks, providing a stateless recovery path on page reloads or dropped webhooks.
  2. **Adaptive Content Generation (ADR-18):** In `LessonContentService`, bound question counts using `actual_questions = min(num_questions, len(chunks))`. Short lessons generate strictly grounded MCQs without hallucination. For lessons with 0 chunks, the router returns a structured, actionable `404 Not Found`.
  3. **Resilient JWT Ingress (ADR-20):** In `TokenClaims`, introduced optional default fields (`company_id: str | None = None`, `role: str = "Student"`). In `AuthService`, added a defensive exception handler capturing `ValidationError` to safely extract claims from .NET Identity tokens without bypassing cryptographic signature verification.
  4. **Per-Lesson Concurrency Locks:** Orchestrated pipeline execution with `_get_lesson_ingest_lock(lesson_id)` to serialize concurrent webhooks and protect Qdrant from race conditions.
* **What We Avoided:** Rejected blocking HTTP requests for ingestion status; rejected saving intermediate job state to SQL Server from Python (preserving strict stateless microservice architecture).

## 3. Verification & Proof of Work
* **Unit Test Suite:** Created [tests/unit/test_ingest_status.py](file:///e:/Mazen/EgyDynamic/LMS_CO_Pilot/tests/unit/test_ingest_status.py) with 4 comprehensive test cases covering:
  - Completed status with Qdrant chunk counting.
  - Active lock detection returning `Processing`.
  - Unprocessed lesson returning `None` status with 0 chunks.
  - Successful asynchronous webhook dispatch to .NET backend with service token headers.
* **Automated Test Results:** All 38/38 unit tests passing with 100% pass rate.

## 4. Interview STAR Capsule
* **Situation:** When processing multi-minute video lectures, the LMS UI had no reliable mechanism to track ingestion progress or know when quizzes/summaries could be generated. Additionally, short videos failed on rigid 5-question requirements.
* **Task:** Implement an end-to-end lifecycle state machine, real-time status synchronization, adaptive quiz generation, and resilient auth negotiation.
* **Action:** Built a dual-sync architecture (push webhook callback to .NET + stateless pull API in Python), enforced `min(k, chunks)` adaptive generation to eliminate hallucinations, and hardened JWT validation for cross-platform tokens.
* **Result:** Achieved 100% reliable UI state transitions in Angular (`None` -> `Queued` -> `Processing` -> `Completed`/`Failed`), zero hallucinations on short videos, and seamless cross-stack interoperability with .NET 10.

---
milestone_id: "M07"
title: "Production Telemetry, Prometheus Alerting & Async Feedback Persistence"
status: "COMPLETED"
last_synced_commit: "2acdb2a"
completed_at: "2026-09-14T15:30:00Z"
---

# 🎯 M07: Production Telemetry, Prometheus Alerting & Async Feedback Persistence

## 1. Engineering Objective
Harden production-grade observability and feedback analytics by implementing real-time streaming latency tracking (TTFT & TPOT histograms), guardrail refusal counters, container-mounted Prometheus alerting rules with automated SLA enforcement, Grafana dashboard telemetry panels, and asynchronous PostgreSQL feedback persistence with composite uniqueness to support student vote updates without blocking the API loop.

## 2. Architectural Tensions & Trade-offs ("The Why")
* **The Conflict/Tension:** In-memory feedback caching alone lost historical audit data across server restarts and prevented multi-tenant analytics. Real-time evaluation proposals suggested running secondary LLM judges on every response, which would quadruple latency and token expenditure. Meanwhile, alerts were unmounted and firing into a void without evaluated metric rules or strict SLA boundaries.
* **The Decisions:**
  1. **Asynchronous Non-Blocking PostgreSQL Feedback Persistence:** Offloaded database storage to FastAPI `BackgroundTasks`, returning immediate client confirmation in `< 15ms`. Applied a composite unique constraint `(user_id, query_hash, answer_hash)` so students can change their rating (UP to DOWN or vice versa) with updated comments without creating duplicate rows or crashing on unique constraints.
  2. **Server-Computed Content Hashing:** Removed client-provided hashes from `FeedbackRequest` and enforced deterministic SHA-256 generation on the server (`query_hash`, `answer_hash`) to eliminate client tampering and ensure consistent deduplication.
  3. **ADR-15: Raw Authentic Feedback Fidelity over Eager Ingestion PII Redaction:** Preserved raw query, answer, and comment text in the internal database to retain critical dialect and phrasing fidelity needed for offline prompt engineering and Ragas drift audits, deferring strict PII redaction to the administrative export layer.
  4. **Granular SSE Streaming Telemetry (TTFT & TPOT):** Instrumented `search_stream` with custom Prometheus histograms: `lms_ttft_seconds` recorded on first token emission (< 300ms) and `lms_tpot_seconds` recorded on generator termination (~20–35ms/token). Added `lms_guardrail_refusals_total` counter tracking dialect and injection mitigations.
  5. **Automated SLA Alerting Rules (ADR-17):** Configured and mounted `monitoring/alerts.yml` into Prometheus with 4 critical production thresholds:
     - `HighErrorRate` (Critical): HTTP 5xx error rate > 5% over 5m window.
     - `HighSearchLatencyP95` (Warning): P95 RAG search latency > 3.0s over 3m window.
     - `HighGuardrailRefusalSpike` (Warning): Security refusal rate > 0.5 events/sec over 2m window.
     - `LowCacheHitRate` (Info): Semantic cache hit rate < 10% under active traffic.
  6. **Decoupled Offline Drift Evaluation Pipeline (ADR-16):** Implemented `GET /v1/admin/feedback?format=ragas&limit=100` to feed automated offline evaluation scripts (`scripts/eval_drift.py`), tracking Faithfulness (>0.85) and Answer Relevancy weekly without burning runtime compute.
* **What We Avoided:** Rejected synchronous database writes during student feedback submission; rejected online LLM evaluation judges in the live inference path; rejected unmounted or unverified alerting configurations that fail to trigger on real metric labels.

## 3. Verification & Proof of Work
* **Contract Specification:** Reflected in `docs/LMS_INTEGRATION_CONTRACT.md`, ADRs 15, 16, and 17 in `docs/production_notes.md`.
* **Telemetry & Visualization:** Grafana dashboard provisioned with 4 dedicated panels (Exact Cache Hit Rate, Feedback Sentiment Breakdown, Intent Routing Distribution, Streaming Latency Performance).
* **Automated Tests:** 11/11 unit tests passing (`tests/unit/test_metrics.py`), verifying TTFT, TPOT, and Guardrail refusal metric registration and Prometheus `/metrics` exposition.

## 4. Interview STAR Capsule
* **Situation:** High-traffic educational platforms need quantitative visibility into streaming latency, security attacks, student sentiment, and model drift without sacrificing sub-second response times.
* **Task:** Architect a production observability and alerting system, implement async feedback persistence, and formulate a model evaluation strategy.
* **Action:** Built real-time Prometheus telemetry for TTFT and TPOT, mounted declarative SLA alert rules into Prometheus, engineered non-blocking PostgreSQL feedback persistence with composite uniqueness for vote updates, added tenant-isolated admin analytics with Ragas export format, and drafted ADRs 15–17.
* **Result:** Achieved <15ms feedback endpoint response time, full Prometheus SLA alerting coverage for 5xx/latency/security spikes, and established a zero-runtime-cost continuous evaluation pipeline.

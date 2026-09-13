---
milestone_id: "M04"
title: "Telemetry, CI/CD & Quantitative Evaluation"
status: "COMPLETED"
last_synced_commit: "e02f7d1"
completed_at: "2026-09-09T22:00:00Z"
---

# 🎯 M04: Telemetry, CI/CD & Quantitative Evaluation

## 1. Engineering Objective
Transition the LMS AI Co-Pilot from "it works on my machine" to an observable, quantitatively validated production system with live metrics, load testing, automated CI/CD, and anti-hallucination guarantees.

## 2. Architectural Tensions & Trade-offs ("The Why")
* **The Conflict/Tension:** Subjective qualitative testing ("the answer looks good to me") gave zero guarantees against regressions when modifying chunking strategies, embeddings, or prompts. Additionally, we lacked visibility into real-time server concurrency, cache hit rates, and downstream latency.
* **The Decision:**
  1. Integrated Prometheus metrics with custom counters/histograms (`rag_queries_total`, `rag_latency_seconds`, `cache_hits_total`) and Grafana monitoring dashboards.
  2. Implemented automated load testing with Locust simulating concurrent student queries.
  3. Integrated **Ragas v0.4+** automated evaluation pipeline against a verified `golden_dataset.jsonl` extracted from real lecture chunks.
  4. Added GitHub Actions CI pipeline running linting, typing (`mypy`), and unit tests on every pull request.
* **What We Avoided:** Rejected manual spreadsheet evaluation; automated Ragas execution writes versioned JSON reports to `tests/eval/results/` and updates `tests/eval/BASELINE.md`.

## 3. Verification & Proof of Work
* **Ragas Quality Benchmark (Recorded in `tests/eval/BASELINE.md`):**
  - **🛡️ Faithfulness:** **0.92** (Target: >= 0.80) — PASSED ✅
  - **🎯 Answer Relevancy:** **0.86** (Target: >= 0.75) — PASSED ✅
* **Load Test Concurrency:** Verified 50 concurrent virtual users with Locust with zero error rate.
* **CI Build:** GitHub Actions workflow (`.github/workflows/main.yml`) green across all test cases.

## 4. Interview STAR Capsule
* **Situation:** Deploying Generative AI to enterprise production requires provable hallucination guardrails and real-time observability.
* **Task:** Establish quantitative quality benchmarks and observability infrastructure before customer release.
* **Action:** Deployed a Prometheus/Grafana telemetry stack, automated Locust load testing, and instituted a Ragas evaluation pipeline anchored to git commits.
* **Result:** Proved 92% Faithfulness and 86% Answer Relevancy objectively, while maintaining sub-second visibility into system latency and cache hit ratios.

---
milestone_id: "M02"
title: "Two-Stage Hybrid Search & Reranking"
status: "COMPLETED"
last_synced_commit: "2a54bfb"
completed_at: "2026-09-06T14:30:00Z"
---

# 🎯 M02: Two-Stage Hybrid Search & Reranking

## 1. Engineering Objective
Construct an enterprise hybrid retrieval pipeline that seamlessly captures both semantic conceptual intent and exact technical tokens (ERP screen IDs, accounting codes, button labels) with sub-second CPU latency.

## 2. Architectural Tensions & Trade-offs ("The Why")
* **The Conflict/Tension:** Pure dense semantic search (BGE-M3 alone) missed exact accounting codes and UI menu clicks. Conversely, pure keyword search (BM25) failed on conceptual student questions. When we added a PyTorch Cross-Encoder reranker for precision, each query took **50 seconds on CPU**, creating an unusable bottleneck.
* **The Decision:** Implemented a two-stage retrieval pipeline:
  1. Stage 1: Dense BGE-M3 (1024d) + Sparse BM25 indexed together in Qdrant with Reciprocal Rank Fusion (RRF).
  2. Stage 2: Quantized ONNX Cross-Encoder (`ms-marco-TinyBERT-L-2-v2` via FlashRank) running directly on CPU.
* **What We Avoided:** Avoided forcing the deployment onto expensive GPU instances, keeping host operational costs near zero while achieving production-grade accuracy.

## 3. Verification & Proof of Work
* **Latency Reduction:** CPU reranking time plunged from **50,000ms down to ~250ms** (a 99.5% latency cut).
* **Trace Logs:** Confirmed in `downloads/search_debugs/` that candidate pools properly merge dense and sparse rankings with explicit score logging.

## 4. Interview STAR Capsule
* **Situation:** Initial RAG queries suffered from poor precision on exact accounting codes, and standard Cross-Encoder reranking was unacceptably slow (50s) on CPU.
* **Task:** Architect a hybrid retrieval engine with sub-second latency and zero GPU dependency.
* **Action:** Built a Qdrant-backed dense/sparse RRF fusion engine followed by an 8-bit quantized ONNX Cross-Encoder running inside an async thread pool.
* **Result:** Slashed query latency to ~250ms on commodity CPUs while maximizing retrieval relevance across both keyword and conceptual queries.

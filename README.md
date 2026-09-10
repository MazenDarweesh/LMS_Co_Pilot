<!-- STATE_TRACKING_ANCHOR: {"last_synced_commit": "180199c", "last_synced_at": "2026-09-10T17:35:00Z", "documented_endpoints": 6} -->

# 🎓 LMS AI Co-Pilot

[![Python](https://img.shields.io/badge/Python-3.13-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Qdrant](https://img.shields.io/badge/Qdrant-1.13.2-FF4D5B?style=flat-square&logo=qdrant&logoColor=white)](https://qdrant.tech)
[![Gemini](https://img.shields.io/badge/Gemini-Flash_Lite_3.5-4285F4?style=flat-square&logo=google&logoColor=white)](https://ai.google.dev)
[![Prometheus](https://img.shields.io/badge/Prometheus-v2.54.1-E6522C?style=flat-square&logo=prometheus&logoColor=white)](https://prometheus.io)
[![Grafana](https://img.shields.io/badge/Grafana-v11.2.0-F46800?style=flat-square&logo=grafana&logoColor=white)](https://grafana.com)
[![CI/CD](https://img.shields.io/badge/CI%2FCD-GitHub_Actions-2088FF?style=flat-square&logo=githubactions&logoColor=white)](.github/workflows/ci.yml)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?style=flat-square&logo=docker&logoColor=white)](https://docker.com)
[![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)](LICENSE)

> **Production-grade AI microservice** that powers context-aware Q&A for Arabic educational content — combining Hybrid RAG, role-based vector retrieval, real-time ingestion pipelines, and live telemetry into a single FastAPI engine.

---

## ✨ Key Features

- ⚡ **Sub-10ms Semantic Caching** — Multi-tenant Qdrant vector similarity cache (`score_threshold = 0.92`) with tenant isolation and RBAC permission awareness; delivers immediate answers in 5–25 ms, eliminating LLM and embedding overhead on repetitive queries
- 🎯 **Quantized Arabic Cross-Encoder** — FlashRank-powered `miniReranker_arabic_v1` running optimized ONNX runtime in a threadpool; slashes reranking latency from ~1,200 ms to ~180 ms with 4x memory savings and zero GPU requirements
- 🔍 **Hybrid RAG Search** — Dense (BGE-M3) + Sparse (BM25) embeddings fused via Reciprocal Rank Fusion (RRF) for superior Arabic retrieval precision
- 🔐 **JWT-Based Permission Filtering** — Vector search is scoped per user role, tenant, module, and level at the Qdrant filter layer
- 📈 **Real-Time Prometheus & Grafana Telemetry** — Native ASGI middleware and custom Prometheus registry exposing `/metrics` with live tracking of Semantic Cache Hit/Miss ratios, active HTTP connections, per-stage RAG latency histograms, and Gemini token consumption, visualized via a pre-provisioned Grafana dashboard (`:3001`)
- ⚡ **Locust Concurrency & Load Testing** — Production-realistic concurrent traffic simulations (`tests/load/locustfile.py`) with weighted multi-tier user scenarios (70% Cache, 20% Cold RAG, 10% Heartbeat), configurable rate-limiting toggles, and LMS mock headers
- 🚀 **Automated GitHub Actions CI/CD** — Complete continuous integration workflow running on every push/PR with containerized PostgreSQL 16 and Qdrant 1.13.2 health services, uv dependency caching, 46-test automated quality gate, and production Docker build verification
- 📡 **Real-Time Ingestion Pipeline** — YouTube audio → Whisper transcription → Gemini MSA normalization → BGE-M3 embedding → Qdrant upsert, all async with SSE progress streaming
- 🔄 **Webhook-Driven Sync** — `.NET 10 LMS` notifies this service on lesson update/delete; vectors and semantic cache entries are re-indexed or purged automatically
- 📝 **Stateless AI Content Generation** — Generates hallucination-free quizzes and pyramid summaries directly from Qdrant vectors without blocking the event loop
- 🗣️ **Arabic Speech AI Utilities** — Built-in WER/CER transcription quality evaluation and mathematical Tafqit for accurate Text-to-Speech
- 📊 **Structured Observability** — Every search request writes a JSON trace file capturing per-stage latency, token usage, reranker scores, and Qdrant point IDs for audit and deduplication
- 🧠 **Stateful Conversational RAG** — LangGraph-powered memory with PostgreSQL checkpointer, featuring a smart Sliding Window and Token Budget Guard to prevent context bloat
- 🧪 **Automated Quality Benchmarking** — Integrated Ragas framework systematically tracking Faithfulness (92%) and Answer Relevancy (86%) against real video transcripts
- 🛡️ **Hardened Production Security** — Strict CORS origin policies, per-endpoint rate limits (`slowapi`), non-root container execution (`appuser`), and Host header validation
- ⚡ **Non-Blocking Architecture** — All heavy operations (embedding, ONNX reranking, file I/O) offloaded via `asyncio.to_thread()` to keep the Uvicorn event loop responsive

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    LMS .NET 10 Backend                          │
│              (JWT Issuer · Webhook Emitter)                     │
└────────────────────┬───────────────────────┬────────────────────┘
                     │ JWT Token              │ Webhook (lesson updated/deleted)
                     ▼                        ▼
┌─────────────────────────────────────────────────────────────────┐
│                  FastAPI AI Engine  (this repo)                 │
│                                                                 │
│  POST /v1/search    POST /v1/ingest/audio      GET /metrics     │
│       │                    │                        │           │
│       ▼                    ▼                        ▼           │
│  ┌─────────────┐    ┌──────────────────────┐   ┌──────────────┐ │
│  │ Auth Filter │    │ Pipeline Orchestrator│   │  Prometheus  │ │
│  │ (JWT + RBAC)│    │ YouTube → Whisper    │   │  Collector   │ │
│  └──────┬──────┘    │ → Gemini Normalize   │   └──────┬───────┘ │
│         │           │ → BGE-M3 Embed       │          │         │
│         ▼           │ → Qdrant Upsert      │          ▼         │
│  ┌───────────────────────────────┐ └───────┘   ┌──────────────┐ │
│  │  Qdrant Semantic Cache Layer  ├──► [HIT:    │  Prometheus  │ │
│  │  (Cosine Sim ≥ 0.92 + Tenant) │    <25ms]   │  (Port 9090) │ │
│  └──────────────┬────────────────┘             └──────┬───────┘ │
│                 │ MISS                                │         │
│                 ▼                                     ▼         │
│  ┌───────────────────────────────┐             ┌──────────────┐ │
│  │ Dense (BGE-M3) + Sparse (BM25)│             │   Grafana    │ │
│  └──────────────┬────────────────┘             │  Dashboard   │ │
│                 ▼                              │ (Port 3001)  │ │
│  ┌───────────────────────────────┐             └──────────────┘ │
│  │ Qdrant Hybrid Search + RRF    │                              │
│  └──────────────┬────────────────┘                              │
│                 ▼                                               │
│  ┌───────────────────────────────┐                              │
│  │ FlashRank ONNX Reranker       │                              │
│  │ (miniReranker_arabic_v1)      │                              │
│  └──────────────┬────────────────┘                              │
│                 ▼                                               │
│  ┌───────────────────────────────┐                              │
│  │ LangGraph State Orchestrator  │                              │
│  │ (PostgreSQL Memory Trimmer)   │                              │
│  └──────────────┬────────────────┘                              │
│                 ▼                                               │
│  ┌───────────────────────────────┐                              │
│  │ Google Gemini 3.5 Flash Lite  │                              │
│  └──────────────┬────────────────┘                              │
│                 ├──► [Async Cache Write]                        │
│                 ▼                                               │
│  ┌───────────────────────────────┐                              │
│  │ JSON Trace + Prometheus Metric│                              │
│  └───────────────────────────────┘                              │
└─────────────────────────────────────────────────────────────────┘
```

---

## 🚀 API Endpoints

| Method | Endpoint | Auth / Protection | Description |
|:------:|:---------|:-----------------:|:------------|
| `POST` | `/v1/search` | JWT · 30 req/min | Hybrid RAG search with role-scoped vector filtering |
| `POST` | `/v1/ingest/audio` | JWT Admin · 5 req/min | Start YouTube → Qdrant ingestion pipeline (async) |
| `GET` | `/v1/ingest/events/{session_id}` | EventSource (SSE) | SSE stream for real-time ingestion progress |
| `POST` | `/v1/webhooks/lesson-updated` | Service Token · 10 req/min | Re-index or delete vectors on LMS content change |
| `GET` | `/v1/lessons/{lesson_id}` | Rate Limited · 20 req/min | Retrieve all processed segments for a lesson |
| `POST` | `/v1/admin/lessons/{lesson_id}/generate-quiz` | JWT Admin · 5 req/min | Generate 5-question MCQs from Qdrant chunks |
| `POST` | `/v1/admin/lessons/{lesson_id}/generate-summary` | JWT Admin · 5 req/min | Generate hierarchical pyramid summary of a lesson |
| `POST` | `/v1/speech/evaluate-quality` | JWT Admin | Calculate WER/CER for AI transcript evaluations |
| `POST` | `/v1/speech/tafqit` | Rate Limited · 60 req/min | Convert numerical digits to Arabic text words |
| `GET` | `/metrics` | Prometheus Scraper / Public | Prometheus metrics endpoint (cache hit rate, latency histograms, token counters) |
| `GET` | `/health` | Public | System health check and environment status |

### Search Request / Response Example

```json
// POST /v1/search
{
  "query": "ما هو بدء التشغيل وانتهاء التشغيل؟",
  "scope": "course",
  "top_k": 10,
  "top_n": 5
}

// Response
{
  "answer": "بدء التشغيل هو البدء في صرف المواد الخام من المخازن [1]...",
  "sources": [
    {
      "chunk_id": "9047c925-...",
      "source_url": "https://youtu.be/0OQAmRrbt3Q?t=120s",
      "reranker_score": 0.9989
    }
  ],
  "metrics": {
    "total_latency_ms": 33921
  }
}
```

---

## 📊 Performance & Telemetry

> *Measured on CPU-only local infrastructure (Intel i7, 16GB RAM) with live Prometheus instrumented traces*

| Stage | Latency | Notes |
|:------|:-------:|:------|
| **Semantic Cache Hit (Vector Lookup)** | **~5–25 ms** | Sub-25ms vector match; 100% LLM token cost reduction |
| **BGE-M3 Embedding** | ~360–440 ms | Dense + Sparse dual concurrent representation |
| **Qdrant Hybrid Search (RRF)** | ~22–175 ms | 200K+ vectors, role & permission filtered |
| **FlashRank ONNX Reranker (`miniReranker_arabic_v1`)** | ~180 ms | Quantized CPU cross-encoder (slashed from ~1,200 ms with PyTorch) |
| **Gemini 3.5 Flash Lite** | ~2,100–5,000 ms | Grounded Arabic RAG answer generation |
| **End-to-End (Cache Miss)** | **~2,700–5,500 ms** | Full retrieval + reranking + generative LLM pipeline |
| **End-to-End (Cache Hit)** | **~460 ms** | Embedding + cache match (zero LLM wait time or cost) |
| **Token Efficiency** | ~1,300–2,200 tokens | Context chunks + prompt + generated response |

### 📈 Load Testing & Observability Telemetry

The service was benchmarked under concurrent multi-user load using **Locust** (`tests/load/locustfile.py`) with a realistic production distribution:
- **70% Cache Queries** (simulating frequent student questions)
- **20% Cold RAG Queries** (new questions triggering hybrid search + LLM generation)
- **10% Health & Heartbeat** (uptime & latency probes)

All metrics are scraped in real-time by **Prometheus** (`:9090`) and visualized on an auto-provisioned **Grafana** dashboard (`:3001`):

```
📊 Telemetry Highlights:
┌──────────────────────────────────────┬───────────────────────┐
│ Metric                               │ Observed Value        │
├──────────────────────────────────────┼───────────────────────┤
│ 🎯 Semantic Cache Hit Rate           │ > 75% under load      │
│ ⚡ Cache Response Turnaround          │ ~460 ms (vs ~4,500 ms)│
│ 🛡️ Error Rate during Concurrency    │ 0.00%                 │
│ 🔌 Active Connection Leaks           │ 0 (Guaranteed finally)│
└──────────────────────────────────────┴───────────────────────┘
```

---

## 🛠️ Tech Stack

| Layer | Technology | Role |
|:------|:-----------|:-----|
| **API** | FastAPI 0.115 + Uvicorn | Async HTTP server |
| **Vector DB & Cache** | Qdrant 1.13.2 | Hybrid search, RRF, semantic caching |
| **Semantic Cache** | Qdrant (`semantic_cache`) | Cosine similarity query caching (threshold ≥ 0.92) |
| **Dense Embedding** | BGE-M3 (BAAI) | Arabic semantic vectors |
| **Sparse Embedding** | BM25 (sentence-transformers) | Keyword matching |
| **Reranker** | FlashRank (`miniReranker_arabic_v1`) | Quantized ONNX cross-encoder rescoring |
| **LLM (RAG)** | Google Gemini 3.5 Flash Lite | Arabic answer generation |
| **Orchestration** | LangGraph | Stateful agent workflows and memory |
| **State DB** | PostgreSQL 16 (asyncpg) | LangGraph persistent memory checkpointer |
| **Observability** | Prometheus v2.54.1 | Native ASGI metrics exporter (`/metrics`) |
| **Telemetry Dashboard** | Grafana 11.2.0 | Auto-provisioned real-time visualization dashboards |
| **Load Testing** | Locust 2.46+ | Multi-user concurrency & stress benchmarking |
| **CI/CD** | GitHub Actions | Automated lint, multi-service testing & container build |
| **LLM (Normalize)**| Google Gemini 3.5 Flash Lite | MSA transcription cleanup |
| **Transcription** | OpenAI Whisper | Audio → text |
| **Auth** | PyJWT + FastAPI Depends | Role-based access control |
| **HTTP Client** | httpx (async) | LMS backend integration |
| **Logging** | structlog | Structured JSON logs |
| **Rate Limiting** | slowapi | Per-endpoint throttling |
| **Evaluation** | Ragas v0.4+ | Automated Faithfulness & Answer Relevancy benchmarking |
| **Streaming** | SSE (sse-starlette) | Real-time pipeline events |
| **Infra** | Docker Compose | Local orchestration |
| **Package Manager** | uv | Fast Python dependency management |

---

## ⚡ Quick Start

```powershell
# 1. Clone and enter project
git clone <repo-url>
cd LMS_CO_Pilot

# 2. Copy environment file and fill in your API keys
cp .env.example .env

# 3. Start PostgreSQL, Qdrant, Prometheus & Grafana (Docker)
docker compose up -d db qdrant prometheus grafana

# 4. Run automated test suite (46 tests)
uv run pytest tests/ -v

# 5. Start development server
uv run uvicorn src.main:app --reload

# 6. (Optional) Simulate concurrent multi-user load
uv run locust -f tests/load/locustfile.py --headless -u 10 -r 2 --run-time 1m

# 7. (Optional) Generate live demo traffic for Grafana
uv run python scripts/generate_traffic.py --requests 20
```

### Access Points

- **API Documentation (Swagger):** `http://localhost:8000/docs`
- **Prometheus Metrics:** `http://localhost:8000/metrics`
- **Prometheus UI:** `http://localhost:9090`
- **Grafana Dashboard:** `http://localhost:3001` *(User: `admin` · Pass: `admin`)*

### Environment Variables

| Variable | Required | Description |
|:---------|:--------:|:------------|
| `GEMINI_API_KEY` | ✅ | Google Gemini API key |
| `QDRANT_URL` | ✅ | Qdrant server URL (default: `http://localhost:6333`) |
| `JWT_SECRET` | ✅ | Must match `.NET LMS` JWT secret |
| `SERVICE_TOKEN` | ✅ | Shared secret for webhook authentication |
| `LMS_BASE_URL` | ✅ | Base URL of the `.NET 10` backend |
| `CORS_ORIGINS` | ⚙️ | Allowed CORS frontend origins (comma-separated or JSON list) |
| `RERANKER_TYPE` | ⚙️ | Reranker engine (`flashrank` or `bge`, default: `flashrank`) |
| `FLASHRANK_MODEL_NAME` | ⚙️ | Quantized ONNX model name (default: `miniReranker_arabic_v1`) |
| `SEMANTIC_CACHE_ENABLED` | ⚙️ | Enable Qdrant vector semantic caching (default: `True`) |
| `SEMANTIC_CACHE_THRESHOLD` | ⚙️ | Cosine similarity threshold for cache hit (default: `0.92`) |
| `QDRANT_SEARCH_CANDIDATES_LIMIT` | ⚙️ | Candidate pool size for Cross-Encoder reranking (default: `8`) |
| `RATE_LIMIT_ENABLED` | ⚙️ | Enable or disable SlowAPI rate limiting (default: `True`) |

---

## 🧪 Quality Evaluation & Benchmarking (Ragas)

To guarantee enterprise-grade answers without hallucination, the RAG pipeline is evaluated automatically using **Ragas v0.4+** against a golden dataset generated from verified video chunks.

### Evaluation Metrics & Baseline

| Metric | Target Threshold | Baseline Score | Status | Description |
|:-------|:----------------:|:--------------:|:------:|:------------|
| **🛡️ Faithfulness** | `>= 0.80` | **`0.92`** (92%) | ✅ PASSED | Assesses whether the generated response is strictly grounded in retrieved context chunks (anti-hallucination) |
| **🎯 Answer Relevancy** | `>= 0.75` | **`0.86`** (86%) | ✅ PASSED | Measures how directly and completely the generated answer addresses the user query |
| **🔍 Context Recall** | `>= 0.70` | *Pending GT* | ⏳ PENDING | Measures retrieval coverage against human ground-truth answers |

### Running Evaluation

```bash
# 1. Generate questions from Qdrant video chunks
uv run python scripts/generate_golden_dataset.py --lessons 556ef8ee-695c-4c2f-900b-36ef1ed98bd8 --per-lesson 2

# 2. Run full evaluation suite
uv run python scripts/run_rag_eval.py

# 3. Quick test with custom limit
uv run python scripts/run_rag_eval.py --limit 2
```

Results and historical runs are logged to `tests/eval/results/` and tracked in `tests/eval/BASELINE.md`.

---

## 🧪 Testing & Quality Assurance

The codebase maintains an automated test suite (46 tests, session-scoped lifespan) covering unit logic, RBAC, integration flows, and Arabic NLP utilities, alongside load testing and CI gates:

```bash
# Run complete unit and integration test suite
uv run pytest tests/ -v

# Run concurrent load test simulation
uv run locust -f tests/load/locustfile.py --headless -u 10 -r 2 --run-time 1m
```

| Test Suite / Workflow | Coverage Area | Tests / Scope | Status |
|:----------------------|:--------------|:-------------:|:------:|
| `tests/integration/test_auth_rbac.py` | JWT authentication & fine-grained permission scopes | 11 | ✅ 100% Passed |
| `tests/integration/test_search_rag.py` | Hybrid RAG retrieval, LangGraph memory, schema validation | 9 | ✅ 100% Passed |
| `tests/integration/test_semantic_cache.py` | Multi-tenant semantic caching, RBAC restriction, invalidation | 5 | ✅ 100% Passed |
| `tests/integration/test_webhooks.py` | LMS lesson update/delete synchronization events | 7 | ✅ 100% Passed |
| `tests/unit/test_memory_trimmer.py` | Token budget guard & sliding window message trimmer | 9 | ✅ 100% Passed |
| `tests/test_arabic_speech.py` | Arabic WER/CER metrics and numerical Tafqit utilities | 3 | ✅ 100% Passed |
| `tests/test_api.py` | System health check and API lifecycle status | 2 | ✅ 100% Passed |
| `tests/load/locustfile.py` | Concurrent stress testing (70% Cache / 20% Cold RAG / 10% Health) | Multi-User | ✅ 0% Error Rate |
| `.github/workflows/ci.yml` | Multi-container CI pipeline (PostgreSQL 16 + Qdrant + Pytest + Docker) | CI Gate | ✅ Passed |

---

## 🗺️ Roadmap

- [x] Hybrid RAG pipeline (Dense + Sparse + RRF)
- [x] Quantized ONNX Arabic reranker (FlashRank `miniReranker_arabic_v1`, ~180ms CPU)
- [x] Multi-tenant Qdrant Semantic Cache (sub-10ms response on repetitive queries)
- [x] JWT authentication + role/tenant/level permission filtering
- [x] YouTube → Whisper → Gemini → Qdrant async ingestion pipeline
- [x] Server-Sent Events (SSE) for real-time ingestion progress
- [x] Webhook-driven auto re-indexing from .NET LMS
- [x] Structured JSON observability traces (latency, token usage, point IDs)
- [x] Antigravity agent system (.agents/ skills, rules, hooks, MCP)
- [x] LangGraph stateful conversational RAG and persistent memory
- [x] Automated RAG quality evaluation (Ragas v0.4+ Faithfulness & Answer Relevancy)
- [x] Production container hardening (non-root execution, Docker Compose health dependencies)
- [x] Prometheus & Grafana live observability stack & hot-reloadable dashboards
- [x] Locust concurrent load testing suite & traffic simulator
- [x] Automated GitHub Actions CI/CD pipeline (PostgreSQL 16, Qdrant 1.13.2, Docker build)
- [ ] PDF ingestion via Marker (Week 9)
- [ ] Production deployment (Docker Swarm / Kubernetes)

---

## 🧠 Agent System

This project ships with a self-improving **Antigravity agent system** (`.agents/`) that encodes
project-specific knowledge for AI-assisted development:

| Component | Purpose |
|:----------|:--------|
| `skills/production-code-audit` | Comprehensive pre-production readiness review (Security, Perf, Config) |
| `skills/search-pipeline-linter` | Unified diagnostic check for RAG RRF pipeline traces |
| `skills/commit-message-generator` | Professional git commit messages generator |
| `skills/service-bootstrapper` | Scaffold new FastAPI services correctly with structlog/lifespan |
| `skills/arabic-assistant` | Dual-purpose tech explainer and MSA text quality/hallucination auditor |
| `skills/architecture-diagram-generator`| Generates standardized Mermaid flowcharts and diagrams |
| `skills/project-chronicle` | Strategic milestone ledger & architectural chronicle (`docs/chronicle/`) |
| `skills/interview-prep-planner` | Living technical interview preparation dossier (`docs/INTERVIEW_PORTFOLIO_MASTER_GUIDE.md`) |
| `skills/blueprint` | Step-by-step construction plans executable cold by coding agents |
| `skills/executing-plans` | Checkpoint-based execution of approved implementation plans |
| `skills/decision-navigator` | Targeted branching questions to resolve architecture decisions |
| `skills/antigravity-chat-restorer` | Diagnoses and restores IDE chat conversations after environment updates |
| `skills/readme-updater` | Auto-updates README.md, Project Chronicle, and Interview Portfolio suite |
| `skills/agent-system-updater` | Detect skill drift and propose diff-style updates |
| `skills/agent-system-planner` | Mine session patterns, propose new workflow components |
| `rules/` | Always-active coding standards (typing, async, service pattern) |
| `hooks/` | Pre-commit linter + post-commit showcase cascade |

---

## 👨‍💻 Author

**Mazen** — Backend & AI Engineer  
Building production AI systems at the intersection of Arabic NLP, vector search, and LLM orchestration.

---

*Last updated by `readme-updater` skill — 2026-09-10*
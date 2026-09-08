# 🚀 LMS AI Co-Pilot: Master Roadmap & Implementation Guide (Weeks 1 & 2)

> **🎯 User Role:** Autonomous Builder (You write and test each component step-by-step).  
> **🛡️ AI Role:** Tech Lead & Architecture Supervisor (I review, verify, and validate each milestone after you complete it).  
> **⚡ Package Manager:** `uv` (Ultra-fast Python package and project manager).

---

## 📊 Current Project Status Re-Evaluation

```text
┌──────────────────────────────────────────┬──────────────┬──────────────────────────────────────────┐
│ Component / Milestone                    │ Status       │ Notes / Current Gap                      │
├──────────────────────────────────────────┼──────────────┼──────────────────────────────────────────┤
│ 🏗️ Clean Architecture Base Structure    │ ✅ COMPLETED │ Base skeleton exists (`src/api`, etc.)   │
│ ⚙️ Structlog & Basic Config              │ ✅ COMPLETED │ Config & structured logging ready        │
│ 📦 Dependency Management via `uv`        │ ⏳ PENDING   │ Need to switch to `uv add` dependencies  │
│ 🎙️ Groq Whisper-v3 Egyptian Audio Ingest │ ⏳ PENDING   │ audio_service currently returns mock data│
│ 🤖 Gemini 1.5 Flash Arabic Normalization │ ⏳ PENDING   │ LLM text cleanup & prompt not integrated │
│ ⚡ Async Concurrency (Semaphore/TaskGroup)│ ⏳ PENDING   │ Needs rate-throttling & async chunking   │
│ 🗄️ PostgreSQL Append-Only Event Store    │ ⏳ PENDING   │ `src/db/` and asyncpg pool not created   │
│ 🌐 Production API Endpoints & Middleware │ ⏳ PENDING   │ Video/PDF ingest endpoints & rate-limits │
│ 🐳 Dockerfile & Pytest-Asyncio Suite     │ ⏳ PENDING   │ Multi-stage Dockerfile & unit tests      │
└──────────────────────────────────────────┴──────────────┴──────────────────────────────────────────┘
```

---

## 🛠️ Global Prerequisites: Setting Up `uv`

If you haven't installed `uv` on your machine yet, install it once:
```powershell
# In PowerShell:
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

To sync your project dependencies with `uv`:
```powershell
# Inside E:\Mazen\EgyDynamic\LMS_CO_Pilot
uv venv
```

---

# 🔴 WEEK 1: Production Python Async + Egyptian Audio Pipeline (~20 hrs)

### 📦 Required Week 1 Packages (Install via `uv`):
```powershell
uv add groq google-genai yt-dlp pydub aiofiles pydantic>=2.6.0 pydantic-settings httpx
```
*(Optional system requirement: `ffmpeg` installed on your machine for audio slicing).*

---

### 📍 Step 1.1: Pydantic V2 Advanced Schemas & Ingestion Contracts
- **Goal:** Build the strict data contracts for the pipeline using Pydantic V2 advanced features.
- **Files to Edit/Create:** `src/models/schemas.py`
- **Core Concepts to Implement:**
  - `BaseModel`, `Field(...)`.
  - `@field_validator` for validating timestamps (`start_time < end_time`, positive values).
  - `@model_validator(mode="after")` to validate YouTube URL format and timestamp query params (`?t=125s`).
  - `.model_dump_json()` serialization.
- **Expected Output Contract:**
  ```json
  {
    "lesson_id": "physics_101_ch1",
    "start_time": 125,
    "end_time": 160,
    "normalized_text": "قانون نيوتن الثاني ينص على أن القوة تساوي الكتلة في التسارع",
    "youtube_url": "https://youtu.be/VIDEO_ID?t=125s"
  }
  ```
- **Checkpoint Action:** Tell me when you finish writing the Pydantic models in `src/models/schemas.py`.

---

### 📍 Step 1.2: YouTube & Audio Downloader / Chunker (`audio_downloader.py`)
- **Goal:** Non-blocking async audio ingestion and chunking without freezing the event loop.
- **Files to Edit/Create:** `src/services/audio_downloader.py`
- **Core Concepts to Implement:**
  - `yt-dlp` async extraction (using `asyncio.to_thread` to prevent blocking the event loop).
  - Splitting large audio files into segments (< 25MB) with overlap using `pydub` or `ffmpeg`.
  - Non-blocking disk I/O using `aiofiles`.
- **Checkpoint Action:** Tell me when you finish implementing the audio downloader and chunking utility.

---

### 📍 Step 1.3: Groq Whisper-v3 Integration with Egyptian Dialect Prompt Injection
- **Goal:** Transcribe Egyptian audio chunks concurrently via Groq API.
- **Files to Edit/Create:** `src/services/audio_service.py`, `src/core/config.py` (add `GROQ_API_KEY`)
- **Core Concepts to Implement:**
  - Async Groq Client (`from groq import AsyncGroq`).
  - Custom domain prompt injection to improve Egyptian dialect speech recognition with technical terms (`FastAPI`, `Qdrant`, `RAG`, `Pydantic`).
  - Handling chunk timestamps and segment metadata.
- **Checkpoint Action:** Tell me when `audio_service.py` is integrated with the real Groq API.

---

### 📍 Step 1.4: Gemini 1.5 Flash Transcript Normalization Engine
- **Goal:** Clean colloquial filler words while preserving timestamps, meaning, and English technical terms.
- **Files to Edit/Create:** `src/services/transcript_normalizer.py`, `src/core/config.py` (add `GEMINI_API_KEY`)
- **Core Concepts to Implement:**
  - Async Gemini client (`google-genai` SDK).
  - Few-shot Arabic Prompting: Remove filler words (مثل: "بص يا سيدي", "يعني", "تمام كده") and normalize to clean formal Arabic (فصحى مبسطة/معاصرة) without modifying original English tech terms.
  - JSON Mode output matching the exact schema.
- **Checkpoint Action:** Tell me when you finish `transcript_normalizer.py`.

---

### 📍 Step 1.5: Production Async Pipeline Orchestrator & Rate Throttling
- **Goal:** Combine downloader, Groq Whisper, and Gemini Normalizer into a concurrent pipeline.
- **Files to Edit/Create:** `src/services/pipeline_orchestrator.py`
- **Core Concepts to Implement:**
  - `asyncio.Semaphore(n)`: Limit concurrent API calls to prevent 429 Rate Limits on Groq and Gemini.
  - `asyncio.TaskGroup` / `asyncio.gather()`: Run audio chunk transcriptions in parallel with atomic error handling.
  - `asyncio.timeout()`: Prevent stalled network calls.
- **Week 1 Deliverable Test:** Process 10 Egyptian dialect audio segments and output the validated JSON array.
- **Checkpoint Action:** Run the pipeline test and notify me to review the final output JSON.

---

# 🔴 WEEK 2: FastAPI Enterprise Architecture & Event Log Schema (~20 hrs)

### 📦 Required Week 2 Packages (Install via `uv`):
```powershell
uv add asyncpg slowapi pypdf python-multipart pytest pytest-asyncio
```

---

### 📍 Step 2.1: PostgreSQL Append-Only Event Store (`agent_event_log`)
- **Goal:** Design the immutable event log storage for auditability and event-sourced agent tracking.
- **Files to Edit/Create:** `src/db/session.py`, `src/db/event_store.py`
- **Core Concepts to Implement:**
  - `asyncpg.create_pool()` connection lifecycle in FastAPI lifespan (`@asynccontextmanager`).
  - Table schema:
    ```sql
    CREATE TABLE IF NOT EXISTS agent_event_log (
        event_id UUID PRIMARY KEY,
        session_id VARCHAR(100) NOT NULL,
        agent_name VARCHAR(50) NOT NULL,
        event_type VARCHAR(50) NOT NULL,
        payload JSONB NOT NULL,
        timestamp TIMESTAMP WITH TIMEZONE DEFAULT NOW()
    );
    ```
  - Append-only insert method (`insert_event(session_id, agent_name, event_type, payload)`).
- **Checkpoint Action:** Tell me when the database connection and event store repository are ready.

---

### 📍 Step 2.2: FastAPI Advanced Dependency Injection (`Depends`)
- **Goal:** Clean architecture DI for database pools, services, and security.
- **Files to Edit/Create:** `src/api/dependencies.py`
- **Core Concepts to Implement:**
  - Injecting database connections from the pool via `Depends(get_db)`.
  - Service providers (`get_audio_service`, `get_event_store`).
- **Checkpoint Action:** Tell me when `dependencies.py` is configured.

---

### 📍 Step 2.3: Production Middlewares (Error Handling, Rate Limiting & SSE Streaming)
- **Goal:** Enterprise reliability and rate limiting.
- **Files to Edit/Create:** `src/core/middleware.py`, `src/api/v1/router.py`
- **Core Concepts to Implement:**
  - Custom Global Exception Handler middleware logging errors with `structlog`.
  - Rate limiting with `slowapi`.
  - Server-Sent Events (`StreamingResponse`) endpoint pattern for LLM token streaming.
- **Checkpoint Action:** Tell me when middlewares and router updates are implemented.

---

### 📍 Step 2.4: Production API Endpoints (`ingest-video`, `ingest-pdf`)
- **Goal:** Expose the complete ingestion pipeline via REST API.
- **Files to Edit/Create:** `src/api/v1/courses.py`, `src/services/pdf_service.py`
- **Endpoints to Implement:**
  - `POST /api/v1/courses/ingest-video` (Triggers Week 1 async audio pipeline and logs event).
  - `POST /api/v1/courses/ingest-pdf` (Extracts text/metadata from course PDFs and logs event).
  - `GET /api/v1/health` (Checks DB connection & external API health).
- **Checkpoint Action:** Tell me when the endpoints are ready for testing in Swagger UI.

---

### 📍 Step 2.5: Multi-Stage Dockerfile & Pytest-Asyncio Verification
- **Goal:** Production containerization and automated testing.
- **Files to Edit/Create:** `Dockerfile`, `docker-compose.yml`, `tests/test_pipeline.py`, `tests/test_api.py`
- **Core Concepts to Implement:**
  - Multi-stage Docker build using `python:3.12-slim` (or 3.11/3.14) with `uv` for fast dependency installation.
  - `docker-compose.yml` defining FastAPI app + PostgreSQL container.
  - Async unit & integration tests using `pytest-asyncio` and `httpx.AsyncClient`.
- **Week 2 Deliverable Test:** Run `uv run pytest` and verify all tests pass.
- **Checkpoint Action:** Send me the test results and Docker build status for final sign-off!

---

## 🎯 How We Will Work Together

1. You start with **Step 1.1**.
2. Write the code in your IDE.
3. When finished, send me a message like: `"خلصت نقطة 1.1 راجع ورايا"`.
4. I will inspect the code, check compliance with DRY, YAGNI, Pydantic V2 standards, and give you immediate feedback or sign off to proceed to the next step!

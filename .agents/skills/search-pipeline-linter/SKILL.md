---
name: search-pipeline-linter
description: >
  Unified diagnostic skill for the LMS Co-Pilot RAG & Ingestion pipeline.
  (1) Lints pipeline code files (search, qdrant, reranker, embedding).
  (2) Analyzes trace JSON logs from downloads/search_debugs/.
  (3) Checks ingestion status/chunk counts of YouTube videos in Qdrant.
  Activates for "search lint", "RAG debug", "trace analysis", "ingestion status", or "check video".
---

# Unified RAG Pipeline & Ingestion Diagnostic Skill

This skill acts as the single source of truth for checking, debugging, and linting the LMS Co-Pilot Hybrid RAG search and ingestion system.

---

## Mode 1: Static Code Linter (search lint)

Verify that the 4 pipeline core files in `src/services/` conform to project constraints:

### Files:
1. `src/services/search_service.py`
2. `src/services/qdrant_service.py`
3. `src/services/reranker_service.py`
4. `src/services/embedding_service.py`

### Checklist:
- **`search_service.py`:**
  - Uses `await embedding_service.get_both_embeddings(query)`
  - Passes `user_entities` to `qdrant_service.hybrid_search()`
  - Logs latency for all stages using `time.time()`
  - Writes debug log with `metrics` and `token_usage`
- **`qdrant_service.py`:**
  - `hybrid_search()` filters by `user_entities`
  - Injects `_qdrant_point_id` into returned payloads
  - Uses `AsyncQdrantClient` and integer timeouts
- **`reranker_service.py`:**
  - Injects `_reranker_score`
  - Runs `model.predict()` in `asyncio.to_thread`
- **`embedding_service.py`:**
  - Uses thread-safe concurrent execution for dense/sparse embeddings

---

## Mode 2: RAG Trace Analysis (RAG debug / trace analysis)

Analyze search trace JSON files from `downloads/search_debugs/search_*.json` (use the most recent file).

### Audit Parameters:
1. **Latency Audit:** Flag if:
   - Embedding > 2000ms ⚠️
   - Qdrant > 500ms ⚠️
   - Reranker > 5000ms ⚠️ (excluding cold start)
   - Gemini > 10000ms ⚠️
2. **Token Efficiency:** Flag total tokens > 2000 ⚠️ (context bloat).
3. **Duplicate Detection:** Flag if any RRF candidates share the same `chunk_id` but have different `point_id`s.
4. **Reranker Scores:** Flag chunks with `score < 0.3` ❌ as poor matches that should be pre-filtered.
5. **Hallucination Spot-check:** Match claims in `gemini_answer` to retrieved chunks.

---

## Mode 3: Ingestion Status Check (ingestion status / check video)

Check if a YouTube video URL has been successfully ingested and indexed.

### Steps:
1. Extract the 11-character video ID from the URL.
2. Query Qdrant points using the scroll endpoint filtering for `source_url` containing the video ID.
3. Calculate:
   - Total number of indexed chunks.
   - Average character length of text.
   - Dialect audit of MSA translation (detect Egyptian/Levantine dialect leaks like "ده" or "مش").
4. Provide a verdict: **Indexed & Healthy** ✅ OR **Needs Re-Ingestion** ❌.

---

## Qdrant REST Reference (Useful for Mode 2 & 3)

### Scroll/Check Video Chunks:
```bash
POST http://localhost:6333/collections/learning_content/points/scroll
{
  "filter": {
    "must": [
      { "key": "source_url", "match": { "text": "<video_id>" } }
    ]
  },
  "limit": 10
}
```

### Delete Duplicates:
```bash
POST http://localhost:6333/collections/learning_content/points/delete
{
  "points": ["<duplicate_point_id>"]
}
```

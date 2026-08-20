---
name: search-pipeline-linter
description: >
  Reviews search pipeline service files (search_service.py, qdrant_service.py,
  reranker_service.py, embedding_service.py) for architecture violations and
  common bugs. Use when adding new features to the pipeline or before committing.
---

# Search Pipeline Linter Skill

You are a code quality reviewer for the LMS Co-Pilot Hybrid RAG search pipeline.
When activated, read and check all 4 pipeline files, then report violations.

## Files to Check

1. `src/services/search_service.py`
2. `src/services/qdrant_service.py`
3. `src/services/reranker_service.py`
4. `src/services/embedding_service.py`

## Mandatory Checklist — Check Every Item

### search_service.py
- [ ] Uses `await embedding_service.get_both_embeddings(query)` — NOT separate dense/sparse calls
- [ ] Passes `user_entities` to `qdrant_service.hybrid_search()` for auth filtering
- [ ] `time.time()` wraps EVERY pipeline stage: embedding, qdrant, reranker, gemini
- [ ] `metrics` dict is populated with all 5 keys: `embedding_latency_ms`, `qdrant_latency_ms`, `reranker_latency_ms`, `gemini_latency_ms`, `total_latency_ms`
- [ ] `token_usage` dict populated from `response.usage_metadata`
- [ ] `_write_search_debug_file()` called with both `metrics=` and `token_usage=` kwargs
- [ ] All `asyncio.to_thread()` wrappers present for blocking calls
- [ ] Type annotations use `dict | None`, not `Optional[dict]`

### qdrant_service.py
- [ ] `hybrid_search()` builds and applies `auth_filter` using `user_entities`
- [ ] Return loop injects `_qdrant_point_id = str(point.id)` into every payload dict
- [ ] `timeout` parameter is `int`, not `float` (AsyncQdrantClient requirement)
- [ ] Uses `AsyncQdrantClient`, not the synchronous `QdrantClient`

### reranker_service.py
- [ ] `_reranker_score` is injected into every returned payload dict
- [ ] `model.predict()` is called inside `asyncio.to_thread()` via `_rerank()` closure
- [ ] `pairs` is constructed as list of tuples: `[(query, str(text)) ...]` — NOT list of lists
- [ ] `# type: ignore` on `.predict()` call includes explanation comment

### embedding_service.py
- [ ] `get_both_embeddings()` uses thread-safe concurrent execution
- [ ] Dense and sparse model calls are inside `asyncio.to_thread()`
- [ ] Singleton `embedding_service` exists at module level

## How to Run the Check

1. Use `view_file` to read each file
2. Go through every checklist item
3. Report all violations before making any fixes
4. Ask user to confirm before applying fixes

## Output Format

```
┌─────────────────────────────────────────────────────────────┐
│ Search Pipeline Lint Report                                 │
├──────────────────────────┬──────────────────────────────────┤
│ File                     │ Status                           │
├──────────────────────────┼──────────────────────────────────┤
│ search_service.py        │ ✅ 8/8 checks passed             │
│ qdrant_service.py        │ ⚠️  3/4 checks (1 violation)    │
│ reranker_service.py      │ ✅ 4/4 checks passed             │
│ embedding_service.py     │ ✅ 3/3 checks passed             │
└──────────────────────────┴──────────────────────────────────┘

❌ Violations Found:
1. [qdrant_service.py] timeout=60.0 (float) — must be int
   Fix: change to timeout=60

📋 Recommended action: Fix violations before committing.
```
